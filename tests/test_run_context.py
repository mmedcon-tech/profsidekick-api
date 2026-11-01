"""
B1/B2 (V2_IMPLEMENTATION_PLAN §5): a member's live run gets only their own
earlier summaries and memories. Integration test: needs the test database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.database.models import Avatar, SessionRun, User, UserMemory
from app.services.personal_template import (
    PERSONAL_TEMPLATE_ID,
    ensure_personal_template,
)
from app.services.summarization_service import (
    get_recent_session_summary,
    get_run_context,
)


def _user(db, role="subscriber"):
    user = User(
        id=uuid.uuid4(),
        username=f"u_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed",
        first_name="T",
        last_name="U",
        role=role,
    )
    db.add(user)
    db.commit()
    return user


def _run(db, session, user, summary=None, minutes_ago=0):
    run = SessionRun(
        id=uuid.uuid4(),
        session_run_id=f"run_{uuid.uuid4().hex[:10]}",
        user_id=user.id,
        session_id=session.id,
        ai_summary=summary,
        start_time=datetime.utcnow() - timedelta(minutes=minutes_ago),
    )
    db.add(run)
    db.commit()
    return run


def _avatar(db, owner):
    ensure_personal_template(db, _user(db, "admin").id)
    avatar = Avatar(
        id=uuid.uuid4(),
        template_id=PERSONAL_TEMPLATE_ID,
        publisher_id=owner.id,
        name="A",
    )
    db.add(avatar)
    db.commit()
    return avatar


def test_a_member_never_gets_another_members_summary(db_session, test_session):
    alice, bob = _user(db_session), _user(db_session)
    _run(db_session, test_session, alice, "Alice: worried about side effects", 30)
    _run(db_session, test_session, bob, "Bob: knee exercises", 60)
    bob_now = _run(db_session, test_session, bob)

    summary, _ = get_run_context(db_session, test_session.session_id, bob_now)

    # Even own legacy summaries bypass individual memory deletion/expiry.
    assert summary is None


def test_a_member_with_no_earlier_runs_gets_no_summary(db_session, test_session):
    alice, carol = _user(db_session), _user(db_session)
    _run(db_session, test_session, alice, "Alice: private topic", 5)
    carol_now = _run(db_session, test_session, carol)

    summary, _ = get_run_context(db_session, test_session.session_id, carol_now)

    assert summary is None


def test_memories_belong_to_the_member_not_the_session_owner(
    db_session, test_session, test_user
):
    avatar = _avatar(db_session, test_user)
    member = _user(db_session)
    db_session.add_all(
        [
            UserMemory(
                id=uuid.uuid4(),
                user_id=member.id,
                avatar_id=avatar.id,
                content="mine",
                kind="preference",
                evidence_quote="my preference",
                confidence=0.9,
            ),
            UserMemory(
                id=uuid.uuid4(),
                user_id=test_user.id,
                avatar_id=avatar.id,
                content="owner",
                kind="preference",
                evidence_quote="owner preference",
                confidence=0.9,
            ),
        ]
    )
    db_session.commit()
    run = _run(db_session, test_session, member)

    _, memories = get_run_context(
        db_session, test_session.session_id, run, avatar_id=avatar.id
    )

    assert memories == ["preference: mine"]


def test_no_avatar_means_no_memories(db_session, test_session):
    member = _user(db_session)
    run = _run(db_session, test_session, member)
    _, memories = get_run_context(
        db_session, test_session.session_id, run, avatar_id=None
    )
    assert memories == []


def test_guest_runs_get_no_summary_or_memories(db_session, test_session):
    guest = _user(db_session)
    _run(db_session, test_session, guest, "an earlier guest's summary", 10)
    run = _run(db_session, test_session, guest)

    summary, memories = get_run_context(
        db_session, test_session.session_id, run, guest_user_uuid=str(guest.id)
    )

    assert (summary, memories) == (None, [])


def test_publisher_chat_keeps_the_session_wide_summary(db_session, test_session):
    alice = _user(db_session)
    _run(db_session, test_session, alice, "Alice's run", 1)
    # This old test's behavior is deliberately superseded: publisher previews
    # must not receive another person's private summary as memory context.
    assert get_recent_session_summary(db_session, test_session.session_id) is None
