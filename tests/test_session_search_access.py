"""
POST /sessions/{id}/search: access checks and course scoping (Stage A, P5).
Integration test: needs the test database (see tests/conftest.py).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.sessions import api as sessions_api
from app.database.connection import get_db
from app.database.models import Course, CourseStudent, User
from app.dependencies.auth import get_optional_user
from app.main import app


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def _fake_retrieve(session_uuid, query, top_k, db, course_id=None):
        calls.append({"session": session_uuid, "course_id": course_id})
        return [{"text": "chunk", "score": 1.0, "source": "slide"}]

    monkeypatch.setattr(sessions_api, "retrieve_context", _fake_retrieve)
    return calls


def _user(db, role):
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


def _search(db_session, caller, session_id, body=None):
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    app.dependency_overrides[get_optional_user] = lambda: caller
    try:
        with TestClient(app) as c:
            return c.post(
                f"/api/sessions/{session_id}/search",
                json=body or {"query": "knee recovery"},
            )
    finally:
        app.dependency_overrides.clear()


def test_owner_can_search_and_course_id_from_the_body_is_ignored(
    db_session, test_user, test_session, captured
):
    other_course = Course(
        id=uuid.uuid4(), course_id=f"c_{uuid.uuid4().hex[:8]}", user_id=test_user.id
    )
    db_session.add(other_course)
    db_session.commit()

    res = _search(
        db_session,
        test_user,
        test_session.session_id,
        {"query": "q", "course_id": str(other_course.id)},
    )

    assert res.status_code == 200
    assert captured == [
        {"session": test_session.id, "course_id": test_session.course_id}
    ]


def test_a_stranger_is_refused(db_session, test_session, captured):
    stranger = _user(db_session, "subscriber")
    res = _search(db_session, stranger, test_session.session_id)
    assert res.status_code == 403
    assert captured == []


def test_an_enrolled_subscriber_needs_a_course_that_allows_subscribers(
    db_session, test_session, captured
):
    member = _user(db_session, "subscriber")
    db_session.add(CourseStudent(course_id=test_session.course_id, user_id=member.id))
    db_session.commit()

    assert _search(db_session, member, test_session.session_id).status_code == 403

    course = db_session.get(Course, test_session.course_id)
    course.allow_subscriber_sessions = True
    db_session.commit()
    assert _search(db_session, member, test_session.session_id).status_code == 200


def test_anonymous_needs_guest_links(db_session, test_session, captured, monkeypatch):
    monkeypatch.setattr(sessions_api.settings, "guest_user_uuid", None)
    assert _search(db_session, None, test_session.session_id).status_code == 401

    monkeypatch.setattr(sessions_api.settings, "guest_user_uuid", str(uuid.uuid4()))
    assert _search(db_session, None, test_session.session_id).status_code == 200


def test_unknown_session_is_404(db_session, test_user, captured):
    assert _search(db_session, test_user, "no-such-session").status_code == 404
