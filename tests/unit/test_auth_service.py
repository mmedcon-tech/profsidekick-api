"""Classical unit tests for sign-in and role gates.

No database. Run with:

    pytest tests/unit -q
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException

from app.config import settings
from app.dependencies.auth import require_admin, require_publisher, require_subscriber
from app.schemas.schemas import UserRegistration
from app.services.auth_service import AuthService


auth = AuthService()


class _Query:
    def __init__(self, row):
        self._row = row

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._row


class _Db:
    """Just enough of a SQLAlchemy session for AuthService."""

    def __init__(self, row=None):
        self._row = row
        self.added = []
        self.committed = False

    def query(self, model):
        return _Query(self._row)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        # A real session refresh loads server defaults such as created_at.
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.utcnow()

    def rollback(self):
        self.committed = False


def _user(**overrides):
    now = datetime.utcnow()
    fields = dict(
        id=uuid.uuid4(),
        username="ssaeed",
        email="ssaeed@example.com",
        password_hash=auth.hash_password("correct-password"),
        first_name="Saeed",
        last_name="Test",
        role="subscriber",
        email_verified=False,
        is_approved=True,
        created_at=now,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_password_hash_matches_only_the_original_password():
    hashed = auth.hash_password("correct-password")
    assert auth.verify_password("correct-password", hashed) is True
    assert auth.verify_password("wrong-password", hashed) is False


def test_access_token_round_trip_and_expiry():
    issued = auth.create_access_token(str(uuid.uuid4()), "ssaeed")
    payload = auth.verify_token(issued["token"])
    assert payload["username"] == "ssaeed"

    expired = jwt.encode(
        {
            "user_id": "x",
            "username": "ssaeed",
            "exp": datetime.utcnow() - timedelta(minutes=5),
            "iat": datetime.utcnow() - timedelta(hours=1),
        },
        settings.secret_key,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(expired)
    assert exc.value.status_code == 401


def test_login_rejects_a_wrong_password():
    result = asyncio.run(auth.login_user(_Db(_user()), "ssaeed", "wrong-password"))
    assert result.success is False
    assert result.token is None
    assert result.message == "Invalid username or password"


def test_login_allows_an_unverified_email_when_the_account_is_approved():
    result = asyncio.run(auth.login_user(_Db(_user(email_verified=False)), "ssaeed", "correct-password"))
    assert result.success is True
    assert result.token
    assert result.user.role == "subscriber"


def test_login_blocks_an_account_that_is_not_approved():
    result = asyncio.run(auth.login_user(_Db(_user(is_approved=False)), "ssaeed", "correct-password"))
    assert result.success is False
    assert result.token is None
    assert "pending approval" in result.message


def test_register_creates_an_account_that_can_sign_in_immediately():
    db = _Db(row=None)
    registration = UserRegistration(
        username="newuser",
        email="newuser@example.com",
        password="correct-password",
        firstName="New",
        lastName="User",
        role="subscriber",
    )
    result = asyncio.run(auth.register_user(db, registration))

    assert result.success is True
    assert result.message == "Registration successful. You can sign in now."
    assert db.committed is True
    created = db.added[0]
    assert created.email_verified is True
    assert created.is_approved is True
    assert created.role == "subscriber"


def test_role_gates_keep_subscribers_out_of_publisher_and_admin_actions():
    subscriber = _user(role="subscriber")
    publisher = _user(role="publisher")
    admin = _user(role="admin")

    with pytest.raises(HTTPException) as publisher_denied:
        asyncio.run(require_publisher(current_user=subscriber))
    assert publisher_denied.value.status_code == 403

    with pytest.raises(HTTPException) as admin_denied:
        asyncio.run(require_admin(current_user=publisher))
    assert admin_denied.value.status_code == 403

    assert asyncio.run(require_subscriber(current_user=subscriber)).role == "subscriber"
    assert asyncio.run(require_publisher(current_user=publisher)).role == "publisher"
    assert asyncio.run(require_admin(current_user=admin)).role == "admin"
