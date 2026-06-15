"""W6 (Phase 6): Subscriber course progress tracking service (R82)."""

import logging
import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.database.models import Course, SessionRun, SessionRunStatus
from app.database.models import Session as SessionModel
from app.database.models.progress import SubscriberCourseProgress

logger = logging.getLogger(__name__)


def update_progress(
    user_id: UUID,
    course_id: UUID,
    session_run_id: UUID,
    time_spent_sec: int,
    db: DBSession,
) -> SubscriberCourseProgress:
    """Upsert subscriber_course_progress for (user_id, course_id).

    completion_pct is recalculated as:
        distinct sessions with at least one COMPLETED run by this subscriber /
        total published sessions in the course
    clamped to [0, 100].

    time_spent_sec is cumulative (incremented, never replaced).
    """
    now = datetime.utcnow()
    progress = (
        db.query(SubscriberCourseProgress)
        .filter(
            SubscriberCourseProgress.user_id == user_id,
            SubscriberCourseProgress.course_id == course_id,
        )
        .first()
    )

    completion_pct = _calculate_completion_pct(user_id, course_id, db)

    if progress:
        progress.time_spent_sec = (progress.time_spent_sec or 0) + max(0, time_spent_sec)
        progress.completion_pct = completion_pct
        progress.session_run_id = session_run_id
        progress.last_session_at = now
        progress.updated_at = now
    else:
        progress = SubscriberCourseProgress(
            id=uuid.uuid4(),
            user_id=user_id,
            course_id=course_id,
            session_run_id=session_run_id,
            completion_pct=completion_pct,
            time_spent_sec=max(0, time_spent_sec),
            last_session_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(progress)

    db.commit()
    db.refresh(progress)
    return progress


def get_progress(user_id: UUID, course_id: UUID, db: DBSession) -> SubscriberCourseProgress | None:
    return (
        db.query(SubscriberCourseProgress)
        .filter(
            SubscriberCourseProgress.user_id == user_id,
            SubscriberCourseProgress.course_id == course_id,
        )
        .first()
    )


def get_all_progress_for_user(user_id: UUID, db: DBSession) -> list[SubscriberCourseProgress]:
    return (
        db.query(SubscriberCourseProgress)
        .filter(SubscriberCourseProgress.user_id == user_id)
        .all()
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _calculate_completion_pct(user_id: UUID, course_id: UUID, db: DBSession) -> float:
    """Return completion percentage based on sessions with completed runs."""
    total_sessions = (
        db.query(func.count(SessionModel.id))
        .filter(
            SessionModel.course_id == course_id,
            SessionModel.is_published.is_(True),
        )
        .scalar()
        or 0
    )
    if total_sessions == 0:
        return 0.0

    completed_session_ids = (
        db.query(SessionRun.session_id)
        .filter(
            SessionRun.user_id == user_id,
            SessionRun.status == SessionRunStatus.COMPLETED,
        )
        .join(SessionModel, SessionModel.id == SessionRun.session_id)
        .filter(SessionModel.course_id == course_id)
        .distinct()
        .count()
    )

    pct = (completed_session_ids / total_sessions) * 100.0
    return min(100.0, round(pct, 2))
