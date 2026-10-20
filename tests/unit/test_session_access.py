"""Who may search a session's knowledge (POST /sessions/{id}/search). No database."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services.session_access import can_search_session

OWNER = uuid.uuid4()
COURSE_OWNER = uuid.uuid4()


def _user(role: str, user_id=None):
    return SimpleNamespace(id=user_id or uuid.uuid4(), role=role)


def _check(user, *, enrolled=False, allows_subscribers=True, guest_links=False):
    return can_search_session(
        user=user,
        session_owner_id=OWNER,
        course_owner_id=COURSE_OWNER,
        course_allows_subscribers=allows_subscribers,
        is_enrolled=enrolled,
        guest_links_enabled=guest_links,
    )


def test_anonymous_callers_need_guest_links_enabled():
    assert _check(None, guest_links=False) is False
    assert _check(None, guest_links=True) is True


def test_admins_and_owners_are_allowed():
    assert _check(_user("admin")) is True
    assert _check(_user("publisher", OWNER)) is True
    assert _check(_user("publisher", COURSE_OWNER)) is True


@pytest.mark.parametrize("role", ["publisher", "subscriber"])
def test_strangers_are_refused(role):
    assert _check(_user(role)) is False


def test_enrolled_subscribers_need_a_course_that_allows_subscribers():
    assert _check(_user("subscriber"), enrolled=True, allows_subscribers=True) is True
    assert _check(_user("subscriber"), enrolled=True, allows_subscribers=False) is False


def test_enrolled_publishers_are_allowed():
    assert _check(_user("publisher"), enrolled=True, allows_subscribers=False) is True
