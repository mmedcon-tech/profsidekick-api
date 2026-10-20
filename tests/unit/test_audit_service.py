"""Unit tests for the append-only audit helper. No database."""

from __future__ import annotations

import uuid

import pytest

from app.database.models import AuditEvent
from app.services.audit_service import record_audit_event


class _Db:
    def __init__(self):
        self.added = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True


def test_records_event_in_the_callers_transaction_without_committing():
    db = _Db()
    actor = uuid.uuid4()
    entity = uuid.uuid4()

    event = record_audit_event(
        db,
        action="knowledge.approved",
        entity_type="knowledge_document",
        entity_id=entity,
        actor_user_id=actor,
        data={"version": 2},
    )

    assert isinstance(event, AuditEvent)
    assert db.added == [event]
    assert db.committed is False
    assert event.entity_id == str(entity)
    assert event.actor_user_id == actor
    assert event.data == {"version": 2}
    assert event.created_at is not None


def test_system_events_have_no_actor_and_default_to_empty_data():
    event = record_audit_event(_Db(), action="job.failed", entity_type="job")
    assert event.actor_user_id is None
    assert event.entity_id is None
    assert event.data == {}


@pytest.mark.parametrize(
    "key", ["password", "password_hash", "access_token", "API_KEY", "client_secret"]
)
def test_refuses_secret_looking_keys(key):
    db = _Db()
    with pytest.raises(ValueError):
        record_audit_event(
            db, action="user.updated", entity_type="user", data={key: "x"}
        )
    assert db.added == []
