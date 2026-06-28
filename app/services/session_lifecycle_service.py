"""W6 (Phase 6): Session lifecycle orchestrator.

Handles all post-stop side effects for a completed session run:
  1. Billing charge (synchronous — must succeed before async work)
  2. Summary generation
  3. Course progress update
  4. Post-session quiz generation

Tasks 2–4 are dispatched as Celery tasks (durable, retryable).  If the
Celery broker is unreachable the function falls back to asyncio.create_task()
for the summary only, logs a warning, and continues without crashing the
stop endpoint.
"""

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from app.database.models import SessionRun
from app.database.models import Session as SessionModel

logger = logging.getLogger(__name__)


def run_post_session_tasks(
    *,
    db: DBSession,
    session: SessionModel,
    session_run: SessionRun,
    user_id: UUID,
    input_tokens: int = 0,
    output_tokens: int = 0,
    is_subscriber: bool = False,
) -> None:
    """Orchestrate all post-session side effects.

    Called by the stop_session_run endpoint after the run is marked COMPLETED
    and billing has been charged.

    Args:
        db: Active DB session (used only for billing; Celery tasks open their own).
        session: The Session ORM object.
        session_run: The SessionRun ORM object (already COMPLETED).
        user_id: The stopping user's UUID.
        input_tokens: Realtime input tokens from the client (for billing).
        output_tokens: Realtime output tokens from the client (for billing).
        is_subscriber: True when the stopping user is a subscriber (billing is gated on this).
    """
    # ── 1. Billing (synchronous) ──────────────────────────────────────────────
    if is_subscriber and (input_tokens > 0 or output_tokens > 0):
        try:
            from app.services import billing_service as _billing
            _billing.charge_usage(
                user_id=user_id,
                operation_type="session_run",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                db=db,
                session_run_id=session_run.id,
            )
            db.commit()
        except Exception as billing_err:
            logger.warning(
                "Billing charge failed for run %s (user=%s): %s",
                session_run.session_run_id, user_id, billing_err,
            )

    # ── 2–4. Background Celery tasks ─────────────────────────────────────────
    session_id_str = session.session_id
    session_run_id_str = session_run.session_run_id
    user_id_str = str(user_id)
    avatar_id_str = str(session.avatar_id) if session.avatar_id else None
    course_id = session.course_id

    # Time spent: derive from start/end if available, else 0
    time_spent_sec = 0
    if session_run.start_time and session_run.end_time:
        delta = (session_run.end_time - session_run.start_time).total_seconds()
        time_spent_sec = max(0, int(delta))

    celery_available = _dispatch_celery_tasks(
        session_id_str=session_id_str,
        session_run_id_str=session_run_id_str,
        user_id_str=user_id_str,
        avatar_id_str=avatar_id_str,
        course_id=course_id,
        time_spent_sec=time_spent_sec,
    )

    if not celery_available:
        # Fallback: fire-and-forget asyncio task for summary only
        _asyncio_fallback_summary(
            db=db,
            session=session,
            session_run=session_run,
            user_id=user_id,
        )


def _dispatch_celery_tasks(
    *,
    session_id_str: str,
    session_run_id_str: str,
    user_id_str: str,
    avatar_id_str: Optional[str],
    course_id,
    time_spent_sec: int,
) -> bool:
    """Dispatch the three Celery tasks. Returns True on success, False if broker unreachable."""
    try:
        from app.worker import (
            run_post_session_summary,
            run_update_course_progress,
            run_generate_quiz,
        )

        run_post_session_summary.delay(
            session_id_str=session_id_str,
            session_run_id_str=session_run_id_str,
            user_id_str=user_id_str,
            avatar_id_str=avatar_id_str,
        )

        if course_id:
            run_update_course_progress.delay(
                user_id_str=user_id_str,
                course_id_str=str(course_id),
                session_run_id_str=session_run_id_str,
                time_spent_sec=time_spent_sec,
            )

        run_generate_quiz.delay(
            session_run_id_str=session_run_id_str,
            user_id_str=user_id_str,
            avatar_id_str=avatar_id_str,
        )

        return True
    except Exception as exc:
        logger.warning(
            "Celery broker unreachable — falling back to asyncio for summary. Error: %s", exc
        )
        return False


def _asyncio_fallback_summary(
    *,
    db: DBSession,
    session: SessionModel,
    session_run: SessionRun,
    user_id: UUID,
) -> None:
    """Best-effort asyncio fallback when Celery is unavailable."""
    try:
        import asyncio as _asyncio
        from app.services.summarization_service import generate_run_summary

        _asyncio.create_task(
            generate_run_summary(
                db=db,
                session=session,
                session_run=session_run,
                slides_details=session.slides_details or [],
                user_id=user_id,
                avatar_id=session.avatar_id,
            )
        )
    except Exception as exc:
        logger.warning("asyncio fallback summary failed: %s", exc)
