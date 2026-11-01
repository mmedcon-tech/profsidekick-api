"""Privacy and evidence boundaries, using a disposable Postgres database."""

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.database.models import (
    Avatar,
    AvatarTemplate,
    MemoryJob,
    SessionRun,
    SessionRunStatus,
    TwinMemoryConsent,
    UserMemory,
    MemoryControl,
)
from app.services import memory_service as m
from app.services.session_service import SessionService
from tests.test_run_context import _user


@pytest.fixture
def memory_twin(db_session, test_user, test_session):
    template = AvatarTemplate(
        id=uuid.uuid4(),
        name="Memory teacher",
        category="Education",
        created_by=test_user.id,
    )
    db_session.add(template)
    db_session.flush()
    avatar = Avatar(
        id=uuid.uuid4(),
        template_id=template.id,
        publisher_id=test_user.id,
        name="Dr Test",
    )
    db_session.add(avatar)
    db_session.flush()
    test_session.avatar_id = avatar.id
    db_session.commit()
    return avatar


def run_for(db, parent, user, quote="I prefer short answers", minutes=1):
    run = SessionRun(
        id=uuid.uuid4(),
        session_run_id=f"run_{uuid.uuid4().hex}",
        user_id=user.id,
        session_id=parent.id,
        start_time=datetime.utcnow() - timedelta(minutes=minutes),
        status=SessionRunStatus.COMPLETED,
        session_run_metadata={"transcript_turns": [{"role": "user", "text": quote}]},
    )
    db.add(run)
    db.commit()
    return run


def change(quote="I prefer short answers", **kwargs):
    return dict(
        action="create",
        type="preference",
        topic="Answer length",
        content="Prefers short answers",
        evidence_quote=quote,
        confidence=0.95,
        **kwargs,
    )


def save(db, avatar, run, changes=None):
    count = m.apply_changes(db, run, avatar, m.transcript(run), changes or [change()])
    db.commit()
    return count


def test_evidence_required_and_user_only(
    db_session, test_session, test_user, memory_twin
):
    run = run_for(db_session, test_session, test_user)
    assert save(db_session, memory_twin, run, [change("invented quote")]) == 0
    assert save(db_session, memory_twin, run) == 1
    item = db_session.query(UserMemory).filter_by(user_id=test_user.id).one()
    assert item.evidence_quote == "I prefer short answers"
    assert item.consent_basis == "education_context"
    assert item.expires_at == m.expiry(item.last_confirmed_at)


def test_repeats_merge_and_later_resolution(
    db_session, test_session, test_user, memory_twin
):
    run = run_for(db_session, test_session, test_user)
    save(db_session, memory_twin, run)
    assert save(db_session, memory_twin, run) == 0
    run2 = run_for(db_session, test_session, test_user)
    assert save(db_session, memory_twin, run2) == 1
    item = db_session.query(UserMemory).filter_by(user_id=test_user.id).one()
    assert item.times_seen == 2
    data = change()
    data.update(action="resolve", id=str(item.id))
    run3 = run_for(db_session, test_session, test_user)
    save(db_session, memory_twin, run3, [data])
    assert item.status == "resolved"
    assert m.context_memories(db_session, test_user.id, memory_twin.id) == []


def test_misconception_requires_real_correction(
    db_session, test_session, test_user, memory_twin
):
    run = run_for(
        db_session, test_session, test_user, "The derivative of x squared is x"
    )
    data = change("The derivative of x squared is x")
    data.update(
        type="misconception",
        topic="derivative",
        content="Unsure of derivative",
        correction_quote="Actually it is 2x",
    )
    assert save(db_session, memory_twin, run, [data]) == 0
    run.session_run_metadata = {
        "transcript_turns": m.transcript(run)
        + [{"role": "assistant", "text": "Actually it is 2x"}]
    }
    assert save(db_session, memory_twin, run, [data]) == 1


def test_healthcare_default_off_and_future_only_opt_in(
    db_session, test_session, test_user, memory_twin
):
    memory_twin.template.category = "Healthcare"
    db_session.commit()
    old = run_for(db_session, test_session, test_user)
    assert save(db_session, memory_twin, old) == 0
    m.enqueue(db_session, old)
    assert db_session.get(MemoryJob, old.id) is None
    m.update_consent(db_session, test_user.id, memory_twin.id, True)
    assert save(db_session, memory_twin, old) == 0
    new = run_for(db_session, test_session, test_user, minutes=-1)
    assert save(db_session, memory_twin, new) == 1
    item = db_session.query(UserMemory).filter_by(user_id=test_user.id).one()
    assert item.consent_basis == "explicit_patient_opt_in"
    assert item.visibility == ["learner"]
    m.update_consent(db_session, test_user.id, memory_twin.id, False)
    assert m.context_memories(db_session, test_user.id, memory_twin.id) == []
    assert db_session.query(UserMemory).filter_by(user_id=test_user.id).count() == 0


def test_healthcare_does_not_store_misconceptions(
    db_session, test_session, test_user, memory_twin
):
    memory_twin.template.category = "Healthcare"
    db_session.commit()
    m.update_consent(db_session, test_user.id, memory_twin.id, True)
    run = run_for(db_session, test_session, test_user, minutes=-1)
    data = change()
    data["type"] = "strength"
    assert save(db_session, memory_twin, run, [data]) == 0


def test_delete_cannot_be_recreated_and_other_person_cannot_read(
    db_session, test_session, test_user, memory_twin
):
    run = run_for(db_session, test_session, test_user)
    save(db_session, memory_twin, run)
    item = db_session.query(UserMemory).filter_by(user_id=test_user.id).one()
    other = _user(db_session)
    with pytest.raises(HTTPException) as exc:
        m.change_item(db_session, other.id, item.id, delete=True)
    assert exc.value.status_code == 404
    db_session.rollback()
    assert m.context_memories(db_session, other.id, memory_twin.id) == []
    m.change_item(db_session, test_user.id, item.id, delete=True)
    assert (
        save(db_session, memory_twin, run_for(db_session, test_session, test_user)) == 0
    )


def test_correction_not_overwritten_and_disable_forgets(
    db_session, test_session, test_user, memory_twin
):
    run = run_for(db_session, test_session, test_user)
    save(db_session, memory_twin, run)
    item = db_session.query(UserMemory).filter_by(user_id=test_user.id).one()
    m.change_item(db_session, test_user.id, item.id, content="Prefers detailed answers")
    save(db_session, memory_twin, run_for(db_session, test_session, test_user))
    db_session.refresh(item)
    assert item.content == "Prefers detailed answers"
    assert item.evidence_quote is None
    m.update_global(db_session, test_user.id, False)
    assert m.dashboard(db_session, test_user.id)["items"] == []
    assert (
        save(db_session, memory_twin, run_for(db_session, test_session, test_user)) == 0
    )


def test_expiry_does_not_renew_on_settings_view_but_renews_on_use(
    db_session, test_session, test_user, memory_twin
):
    save(db_session, memory_twin, run_for(db_session, test_session, test_user))
    item = db_session.query(UserMemory).filter_by(user_id=test_user.id).one()
    before = item.expires_at
    m.dashboard(db_session, test_user.id)
    assert item.expires_at == before
    assert m.context_memories(db_session, test_user.id, memory_twin.id)
    assert item.expires_at >= before
    item.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert m.context_memories(db_session, test_user.id, memory_twin.id) == []
    assert db_session.query(UserMemory).filter_by(user_id=test_user.id).count() == 0
    assert m.expiry(datetime(2024, 2, 29)) == datetime(2025, 2, 28)


def test_expert_requires_education_owner_enrollment_and_disclosure(
    db_session, test_session, test_user, memory_twin
):
    learner = _user(db_session)
    test_session.course.students.append(learner)
    db_session.commit()
    run = run_for(db_session, test_session, learner)
    save(db_session, memory_twin, run)
    assert m.education_view(db_session, test_user.id, memory_twin.id)["counts"] == []
    m.update_consent(db_session, learner.id, memory_twin.id, True, True)
    result = m.education_view(db_session, test_user.id, memory_twin.id, learner.id)
    assert len(result["items"]) == 1
    assert "evidence_quote" not in result["items"][0]
    assert (
        m.education_view(db_session, test_user.id, memory_twin.id)["counts"][0]["count"]
        == 1
    )
    test_session.course.students.remove(learner)
    db_session.commit()
    assert m.education_view(db_session, test_user.id, memory_twin.id)["counts"] == []
    with pytest.raises(HTTPException):
        m.education_view(db_session, learner.id, memory_twin.id)


def test_api_ownership_settings_and_validation(
    client, db_session, test_user, test_session, memory_twin
):
    save(db_session, memory_twin, run_for(db_session, test_session, test_user))
    response = client.get("/api/memory")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert (
        client.patch(
            f"/api/memory/items/{item['id']}", json={"content": " "}
        ).status_code
        == 422
    )
    assert (
        client.patch("/api/memory/settings", json={"enabled": False}).status_code == 204
    )
    assert client.get("/api/memory").json()["items"] == []
    assert client.delete(f"/api/memory/items/{uuid.uuid4()}").status_code == 404


@pytest.mark.asyncio
async def test_stop_preserves_evidence_and_is_idempotent(
    db_session, test_user, test_session, memory_twin
):
    run = run_for(db_session, test_session, test_user)
    run.status = SessionRunStatus.ACTIVE
    db_session.commit()
    service = SessionService()
    await service.stop_session_run(
        db_session,
        test_session.session_id,
        run.session_run_id,
        {"duration": 42, "transcript_turns": []},
    )
    assert m.transcript(run)[0]["text"] == "I prefer short answers"
    await service.stop_session_run(
        db_session, test_session.session_id, run.session_run_id, {}
    )
    assert m.transcript(run)


@pytest.mark.asyncio
async def test_durable_job_own_connection_and_retry(
    db_session, test_user, test_session, memory_twin
):
    from tests.conftest import TestSessionLocal

    run = run_for(db_session, test_session, test_user)
    m.enqueue(db_session, run)
    m.enqueue(db_session, run)
    assert db_session.query(MemoryJob).filter_by(run_id=run.id).count() == 1
    with patch("app.database.connection.SessionLocal", TestSessionLocal), patch.object(
        m, "extract", AsyncMock(side_effect=RuntimeError("provider error"))
    ):
        assert await m.process_job(run.id)
    db_session.expire_all()
    job = db_session.get(MemoryJob, run.id)
    assert job.status == "pending" and job.attempts == 1
    job.available_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    with patch("app.database.connection.SessionLocal", TestSessionLocal), patch.object(
        m, "extract", AsyncMock(return_value=[change()])
    ):
        assert await m.process_job(run.id)
        assert not await m.process_job(run.id)
    db_session.expire_all()
    assert db_session.get(MemoryJob, run.id).status == "done"
    assert db_session.query(UserMemory).filter_by(user_id=test_user.id).count() == 1


def test_forget_blocks_old_jobs_even_if_model_changes_topic(
    db_session, test_session, test_user, memory_twin
):
    run = run_for(db_session, test_session, test_user)
    save(db_session, memory_twin, run)
    item = db_session.query(UserMemory).filter_by(user_id=test_user.id).one()
    m.change_item(db_session, test_user.id, item.id, delete=True)
    data = change()
    data["topic"] = "Different wording of answer preference"
    assert save(db_session, memory_twin, run, [data]) == 0
    assert db_session.query(UserMemory).filter_by(user_id=test_user.id).count() == 0


@pytest.mark.asyncio
async def test_consent_revoked_during_extraction_cannot_commit(
    db_session, test_user, test_session, memory_twin
):
    from tests.conftest import TestSessionLocal

    run = run_for(db_session, test_session, test_user)
    m.enqueue(db_session, run)

    async def revoke_then_return(*args):
        with TestSessionLocal() as other:
            m.update_global(other, test_user.id, False)
        return [change()]

    with patch("app.database.connection.SessionLocal", TestSessionLocal), patch.object(
        m, "extract", side_effect=revoke_then_return
    ):
        assert await m.process_job(run.id)
    db_session.expire_all()
    assert db_session.query(UserMemory).filter_by(user_id=test_user.id).count() == 0


def test_guest_and_other_twins_never_receive_memories(
    db_session, test_session, test_user, memory_twin
):
    run = run_for(db_session, test_session, test_user)
    with patch.object(m.settings, "guest_user_uuid", str(test_user.id)):
        assert save(db_session, memory_twin, run) == 0
    save(db_session, memory_twin, run)
    other = Avatar(
        id=uuid.uuid4(),
        template_id=memory_twin.template_id,
        publisher_id=test_user.id,
        name="Other",
    )
    db_session.add(other)
    db_session.commit()
    assert m.context_memories(db_session, test_user.id, other.id) == []


def test_enrollment_in_another_course_does_not_expose_private_run(
    db_session, test_session, test_user, memory_twin
):
    from app.database.models import Course, Session as SessionModel

    learner = _user(db_session)
    test_session.course.students.append(learner)
    private_course = Course(
        id=uuid.uuid4(),
        course_id=f"course_{uuid.uuid4().hex}",
        user_id=test_user.id,
        name="Private",
    )
    db_session.add(private_course)
    db_session.flush()
    private_session = SessionModel(
        id=uuid.uuid4(),
        session_id=f"session_{uuid.uuid4().hex}",
        user_id=test_user.id,
        course_id=private_course.id,
        avatar_id=memory_twin.id,
    )
    db_session.add(private_session)
    db_session.commit()
    save(db_session, memory_twin, run_for(db_session, private_session, learner))
    m.update_consent(db_session, learner.id, memory_twin.id, True, True)
    assert m.education_view(db_session, test_user.id, memory_twin.id)["counts"] == []
