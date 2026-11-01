"""
Live sessions tell the client the avatar's profession, and consultation stays a
consultation. Integration test: needs the test database (see tests/conftest.py).
"""

import uuid

import pytest

from app.api.sessions.api import _session_profession
from app.database.models import Avatar, AvatarTemplate
from app.schemas.schemas import SessionCreateRequest
from app.services.session_service import SESSION_MODES


def _avatar(db, user, category):
    template = AvatarTemplate(
        id=uuid.uuid4(), name="Twin", category=category, created_by=user.id
    )
    db.add(template)
    db.flush()
    avatar = Avatar(
        id=uuid.uuid4(), template_id=template.id, publisher_id=user.id, name="Dr Twin"
    )
    db.add(avatar)
    db.flush()
    return avatar


def test_healthcare_avatar_session_reports_healthcare(
    db_session, test_user, test_session
):
    test_session.avatar_id = _avatar(db_session, test_user, "Healthcare").id
    db_session.commit()
    assert _session_profession(db_session, test_session.session_id) == "healthcare"


def test_session_without_avatar_reports_no_profession(db_session, test_session):
    assert _session_profession(db_session, test_session.session_id) is None


def test_unknown_session_reports_no_profession(db_session):
    assert _session_profession(db_session, "session_missing") is None


@pytest.mark.parametrize("mode", ["teaching", "examination", "consultation"])
def test_consultation_is_a_valid_session_mode(mode):
    assert mode in SESSION_MODES
    request = SessionCreateRequest(
        courseId="c", className="Knee prep", duration=30, sessionMode=mode
    )
    assert request.sessionMode == mode
