"""
Persist voice/text transcript turns on session runs.

Turns are stored in ``session_run.session_run_metadata['transcript_turns']``
as a list of {id, role, text, captured_at} dicts — same pattern as subscriber chat.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import SessionRun

_MAX_TURNS = 500


def _get_run(db: Session, session_run_id: str) -> Optional[SessionRun]:
    return db.query(SessionRun).filter(SessionRun.session_run_id == session_run_id).first()


def _assert_owner(run: SessionRun, user_id: Any) -> None:
    if str(run.user_id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not your session run.",
        )


def get_transcript_turns(db: Session, session_run_id: str, user_id: Any) -> List[Dict[str, Any]]:
    run = _get_run(db, session_run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found.")
    _assert_owner(run, user_id)
    meta = run.session_run_metadata or {}
    return list(meta.get("transcript_turns", []))


def append_transcript_turn(
    db: Session,
    session_run_id: str,
    user_id: Any,
    role: str,
    text: str,
    captured_at: Optional[str] = None,
) -> Dict[str, Any]:
    if role not in ("user", "assistant"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="role must be user or assistant",
        )

    trimmed = (text or "").strip()
    if not trimmed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")

    run = _get_run(db, session_run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found.")
    _assert_owner(run, user_id)

    turn = {
        "id": str(uuid.uuid4()),
        "role": role,
        "text": trimmed,
        "captured_at": captured_at or datetime.utcnow().isoformat(),
    }

    meta = dict(run.session_run_metadata or {})
    turns = list(meta.get("transcript_turns", []))
    turns.append(turn)
    meta["transcript_turns"] = turns[-_MAX_TURNS:]
    run.session_run_metadata = meta
    run.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return turn
