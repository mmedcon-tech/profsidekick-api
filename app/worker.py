"""W6 (Phase 6): Celery worker — durable background task queue backed by Redis.

Tasks migrated from asyncio.create_task() at Wave 6:
  - run_post_session_summary   (previously asyncio background)
  - run_update_course_progress (new — R82)
  - run_generate_quiz          (new — R83)

Each task creates its own DB session so it is fully independent of the
FastAPI request lifecycle.  Async service functions are wrapped with
asyncio.run().
"""

import asyncio
import logging
from typing import Optional

from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "myos",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


def _get_db():
    """Create a standalone SQLAlchemy session for use inside Celery tasks."""
    from app.database.connection import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="myos.run_post_session_summary",
    max_retries=3,
    default_retry_delay=30,
)
def run_post_session_summary(
    self,
    session_id_str: str,
    session_run_id_str: str,
    user_id_str: str,
    avatar_id_str: Optional[str] = None,
) -> None:
    """Generate and store an AI summary for a completed session run."""
    from app.database.connection import SessionLocal
    from app.database.models import Session as SessionModel, SessionRun
    from app.services.summarization_service import generate_run_summary

    db = SessionLocal()
    try:
        session = db.query(SessionModel).filter(SessionModel.session_id == session_id_str).first()
        session_run = db.query(SessionRun).filter(SessionRun.session_run_id == session_run_id_str).first()
        if not session or not session_run:
            logger.warning(
                "run_post_session_summary: session or run not found (%s / %s)",
                session_id_str, session_run_id_str,
            )
            return

        import uuid
        user_id = uuid.UUID(user_id_str)
        avatar_id = uuid.UUID(avatar_id_str) if avatar_id_str else None

        asyncio.run(
            generate_run_summary(
                db=db,
                session=session,
                session_run=session_run,
                slides_details=session.slides_details or [],
                user_id=user_id,
                avatar_id=avatar_id,
            )
        )
    except Exception as exc:
        logger.error("run_post_session_summary failed: %s", exc, exc_info=True)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error("run_post_session_summary: max retries exceeded for run %s", session_run_id_str)
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="myos.run_update_course_progress",
    max_retries=3,
    default_retry_delay=15,
)
def run_update_course_progress(
    self,
    user_id_str: str,
    course_id_str: str,
    session_run_id_str: str,
    time_spent_sec: int = 0,
) -> None:
    """Upsert subscriber_course_progress after a session run completes (R82)."""
    from app.database.connection import SessionLocal
    from app.services.progress_service import update_progress

    import uuid
    db = SessionLocal()
    try:
        update_progress(
            user_id=uuid.UUID(user_id_str),
            course_id=uuid.UUID(course_id_str),
            session_run_id=uuid.UUID(session_run_id_str),
            time_spent_sec=max(0, time_spent_sec),
            db=db,
        )
    except Exception as exc:
        logger.error("run_update_course_progress failed: %s", exc, exc_info=True)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error(
                "run_update_course_progress: max retries exceeded for run %s",
                session_run_id_str,
            )
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="myos.run_generate_quiz",
    max_retries=2,
    default_retry_delay=60,
)
def run_generate_quiz(
    self,
    session_run_id_str: str,
    user_id_str: str,
    avatar_id_str: Optional[str] = None,
) -> None:
    """Generate a post-session quiz and store the AssessmentResult (R83)."""
    from app.database.connection import SessionLocal
    from app.services.assessment_service import generate_quiz

    import uuid
    db = SessionLocal()
    try:
        generate_quiz(
            session_run_id=uuid.UUID(session_run_id_str),
            user_id=uuid.UUID(user_id_str),
            avatar_id=uuid.UUID(avatar_id_str) if avatar_id_str else None,
            db=db,
        )
    except Exception as exc:
        logger.error("run_generate_quiz failed: %s", exc, exc_info=True)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error("run_generate_quiz: max retries exceeded for run %s", session_run_id_str)
    finally:
        db.close()
