"""W6 (Phase 6): Post-session quiz generation service (R83)."""

import json
import logging
import uuid
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.database.models import SessionRun
from app.database.models import Session as SessionModel
from app.database.models.progress import AssessmentResult

logger = logging.getLogger(__name__)

_QUIZ_SYSTEM_PROMPT = (
    "You are an educational assessment expert. "
    "Given a session description and topic, generate 5 multiple-choice quiz questions. "
    "Return a valid JSON array where each element is an object with keys: "
    "question (string), options (array of 4 strings), correct_index (0-3 integer), "
    "explanation (string). Respond ONLY with the JSON array — no markdown, no prose."
)


def generate_quiz(
    session_run_id: UUID,
    user_id: UUID,
    avatar_id: Optional[UUID],
    db: DBSession,
) -> Optional[AssessmentResult]:
    """Generate a 5-question post-session quiz using GPT-4o-mini and store the result (R83).

    Returns None if:
    - A result already exists for this session run (idempotent).
    - The session run or session cannot be found.
    - quiz generation is disabled on the publisher's avatar profile.
    - The OpenAI call fails (failure is logged and swallowed to keep stop non-blocking).
    """
    existing = (
        db.query(AssessmentResult)
        .filter(AssessmentResult.session_run_id == session_run_id)
        .first()
    )
    if existing:
        return existing

    session_run = db.query(SessionRun).filter(SessionRun.id == session_run_id).first()
    if not session_run:
        logger.warning("generate_quiz: session_run %s not found", session_run_id)
        return None

    session = db.query(SessionModel).filter(SessionModel.id == session_run.session_id).first()
    if not session:
        logger.warning("generate_quiz: session for run %s not found", session_run_id)
        return None

    # Respect publisher opt-in flag (R83) — quiz requires explicit opt-in via avatar profile
    effective_avatar_id = avatar_id or session.avatar_id
    if not effective_avatar_id:
        logger.info("generate_quiz: no avatar_id on run %s — quiz generation skipped", session_run_id)
        return None

    from app.database.models import PublisherAvatarProfile
    profile = (
        db.query(PublisherAvatarProfile)
        .filter(PublisherAvatarProfile.publisher_avatar_id == effective_avatar_id)
        .first()
    )
    if not profile or not profile.post_session_quiz_enabled:
        logger.info("generate_quiz: quiz not enabled for avatar %s", effective_avatar_id)
        return None

    session_topic = session.title or session.class_name or "the session topic"
    description = session.description or ""

    user_prompt = (
        f"Session title: {session_topic}\n"
        f"Description: {description}\n\n"
        "Generate 5 multiple-choice questions that test understanding of the key concepts "
        "covered in this session."
    )

    try:
        import openai
        client = openai.OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _QUIZ_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=1500,
        )
        raw = response.choices[0].message.content or "[]"
        quiz_questions = json.loads(raw)
        if not isinstance(quiz_questions, list):
            raise ValueError("Quiz response is not a JSON array")
    except Exception as exc:
        logger.warning(
            "generate_quiz: OpenAI call failed for run %s: %s", session_run_id, exc
        )
        return None

    result = AssessmentResult(
        id=uuid.uuid4(),
        session_run_id=session_run_id,
        user_id=user_id,
        avatar_id=avatar_id,
        quiz_questions=quiz_questions,
        score=None,
        generated_at=datetime.utcnow(),
    )
    db.add(result)
    try:
        db.commit()
        db.refresh(result)
    except Exception as exc:
        db.rollback()
        logger.warning("generate_quiz: DB commit failed for run %s: %s", session_run_id, exc)
        return None

    return result


def get_assessment(session_run_id: UUID, db: DBSession) -> Optional[AssessmentResult]:
    return (
        db.query(AssessmentResult)
        .filter(AssessmentResult.session_run_id == session_run_id)
        .first()
    )
