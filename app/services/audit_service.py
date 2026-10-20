"""
Append-only audit trail (ADR 0013).

record_audit_event() adds a row to the caller's session without committing, so
the event commits or rolls back together with the change it describes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.database.models import AuditEvent

# Keys whose values must never be written to the audit trail.
_FORBIDDEN_KEYS = {
    "password",
    "password_hash",
    "token",
    "secret",
    "api_key",
    "authorization",
}


def _check_data(data: Dict[str, Any]) -> None:
    for key in data:
        if any(word in key.lower() for word in _FORBIDDEN_KEYS):
            raise ValueError(f"Audit data must not contain secrets (key: {key!r})")


def record_audit_event(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: Optional[Any] = None,
    actor_user_id: Optional[Any] = None,
    data: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    payload = dict(data or {})
    _check_data(payload)
    event = AuditEvent(
        id=uuid.uuid4(),
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        data=payload,
        created_at=datetime.utcnow(),
    )
    db.add(event)
    return event
