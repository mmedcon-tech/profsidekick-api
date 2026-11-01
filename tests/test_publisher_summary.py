"""
GET /api/publisher/analytics/summary (V2_IMPLEMENTATION_PLAN phase 1).
Integration test: needs the test database (see tests/conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.database.connection import get_db
from app.database.models import Avatar, Course, CourseStudent, SessionRun, User
from app.database.models import Session as SessionModel
from app.dependencies.auth import get_current_user
from app.main import app
from app.services.personal_template import (
    PERSONAL_TEMPLATE_ID,
    ensure_personal_template,
)
from app.services.publisher_analytics_service import build_publisher_summary

NOW = datetime(2026, 10, 20, 12, 0, 0)


def _user(db, role="subscriber", first="Mem"):
    user = User(
        id=uuid.uuid4(),
        username=f"u_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed",
        first_name=first,
        last_name="Ber",
        role=role,
    )
    db.add(user)
    db.commit()
    return user


def _workspace(db, publisher, *, course_active=True):
    ensure_personal_template(db, _user(db, "admin").id)
    avatar = Avatar(
        id=uuid.uuid4(),
        template_id=PERSONAL_TEMPLATE_ID,
        publisher_id=publisher.id,
        name="Twin",
        is_published=True,
    )
    draft = Avatar(
        id=uuid.uuid4(),
        template_id=PERSONAL_TEMPLATE_ID,
        publisher_id=publisher.id,
        name="Draft",
    )
    course = Course(
        id=uuid.uuid4(),
        course_id=f"c_{uuid.uuid4().hex[:8]}",
        user_id=publisher.id,
        name="Knee recovery",
        is_active=course_active,
    )
    db.add_all([avatar, draft, course])
    db.flush()
    session = SessionModel(
        id=uuid.uuid4(),
        session_id=f"s_{uuid.uuid4().hex[:8]}",
        user_id=publisher.id,
        course_id=course.id,
        avatar_id=avatar.id,
    )
    db.add(session)
    db.commit()
    return avatar, course, session


def _run(db, session, user, start, minutes=None):
    db.add(
        SessionRun(
            id=uuid.uuid4(),
            session_run_id=f"r_{uuid.uuid4().hex[:10]}",
            user_id=user.id,
            session_id=session.id,
            start_time=start,
            end_time=start + timedelta(minutes=minutes) if minutes else None,
        )
    )
    db.commit()


def _enrol(db, course, user, when):
    db.add(
        CourseStudent(
            id=uuid.uuid4(), course_id=course.id, user_id=user.id, enrollment_date=when
        )
    )
    db.commit()


def test_counts_only_this_publishers_activity(db_session):
    me, other = _user(db_session, "publisher"), _user(db_session, "publisher")
    _, _, my_session = _workspace(db_session, me)
    _, _, their_session = _workspace(db_session, other)
    alice, bob, guest = _user(db_session), _user(db_session), _user(db_session)

    _run(db_session, my_session, alice, NOW - timedelta(days=2), minutes=30)
    _run(db_session, my_session, alice, NOW - timedelta(days=1), minutes=15)
    _run(db_session, my_session, me, NOW - timedelta(days=1), minutes=10)  # own preview
    _run(db_session, my_session, guest, NOW - timedelta(days=1), minutes=5)
    _run(db_session, their_session, bob, NOW - timedelta(days=1), minutes=99)

    s = build_publisher_summary(
        db_session, me.id, now=NOW, guest_user_uuid=str(guest.id)
    )

    assert s["twins"] == {"draft": 1, "published": 1}
    assert s["active_members_30d"] == 1  # alice; not me, not the shared guest, not bob
    assert s["sessions_this_month"] == 4
    assert s["minutes_this_month"] == 60
    assert s["average_goal_completion"] is None
    assert s["review_submissions"] is None
    assert s["open_escalations"] is None


def test_at_risk_flags_members_inactive_for_14_days_with_a_reason(db_session):
    me = _user(db_session, "publisher")
    _, course, session = _workspace(db_session, me)
    lapsed, fresh, never = (
        _user(db_session, first="Lapsed"),
        _user(db_session),
        _user(db_session, first="Never"),
    )
    for member in (lapsed, fresh, never):
        _enrol(db_session, course, member, NOW - timedelta(days=40))
    _run(db_session, session, lapsed, NOW - timedelta(days=21))
    _run(db_session, session, fresh, NOW - timedelta(days=3))

    at_risk = build_publisher_summary(db_session, me.id, now=NOW)["at_risk"]

    by_name = {r["member_name"]: r for r in at_risk}
    assert set(by_name) == {"Lapsed Ber", "Never Ber"}
    assert by_name["Lapsed Ber"]["reason"] == "No session in 21 days"
    assert (
        by_name["Never Ber"]["reason"]
        == "Enrolled 40 days ago and has not started a session"
    )
    assert at_risk[0]["member_name"] == "Never Ber"  # longest inactive first


def test_inactive_courses_raise_no_alerts(db_session):
    me = _user(db_session, "publisher")
    _, course, _ = _workspace(db_session, me, course_active=False)
    _enrol(db_session, course, _user(db_session), NOW - timedelta(days=60))
    assert build_publisher_summary(db_session, me.id, now=NOW)["at_risk"] == []


def test_endpoint_requires_a_publisher(db_session):
    member = _user(db_session)
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    app.dependency_overrides[get_current_user] = lambda: member
    try:
        with TestClient(app) as c:
            assert c.get("/api/publisher/analytics/summary").status_code == 403
            publisher = _user(db_session, "publisher")
            app.dependency_overrides[get_current_user] = lambda: publisher
            body = c.get("/api/publisher/analytics/summary").json()
            assert body["twins"] == {"draft": 0, "published": 0}
            assert body["at_risk_rules_evaluated"] == ["inactive_14_days"]
    finally:
        app.dependency_overrides.clear()
