"""Legacy run-summary compatibility and consent-gated memory context.

New persistent memory is extracted by memory_service from real transcripts.
Unstructured old summaries are never reused as future personal context.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.database.models import SessionRun
from app.database.models import Session as SessionModel

logger = logging.getLogger(__name__)
_openai = AsyncOpenAI(api_key=settings.openai_api_key)

_SUMMARY_SYSTEM = """You are an academic session analyzer. Given information about a teaching session, produce a structured JSON summary with the following keys:

{
  "summary": "2–4 sentence plain-text summary of what was covered and how the student performed",
  "topics_covered": ["topic1", "topic2"],
  "struggles": ["area where student struggled"],
  "strengths": ["area where student did well"],
  "memory_signals": ["Short bullet about the student — max 15 words each — e.g. 'Prefers step-by-step explanations', 'Struggles with recursion base cases'"]
}

Be concise and factual. Do not invent information not present in the input."""


async def _call_llm(prompt: str) -> Optional[dict]:
    try:
        response = await _openai.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        return json.loads(raw)
    except Exception as e:
        logger.error(f"summarization LLM call failed: {e}")
        return None


def _build_input_prompt(
    session: SessionModel,
    session_run: SessionRun,
    slides_details: list,
) -> str:
    duration_mins = None
    if session_run.start_time and session_run.end_time:
        duration_mins = int(
            (session_run.end_time - session_run.start_time).total_seconds() / 60
        )

    meta = session_run.session_run_metadata or {}
    slides_completed = meta.get("slides_completed")
    student_slides = [s for s in slides_details if s.get("source") != "solution"]

    lines = [
        f"Session class: {session.class_name or 'Unknown'}",
        f"Duration: {duration_mins} minutes" if duration_mins else "Duration: unknown",
        f"Role used: {session_run.role_at_start or 'Not specified'}",
        f"Total slides: {len(student_slides)}",
        (
            f"Slides completed: {slides_completed}"
            if slides_completed
            else "Slides completed: unknown"
        ),
    ]

    if student_slides:
        slide_titles = [
            s.get("title", f"Slide {s.get('slideNumber', i+1)}")
            for i, s in enumerate(student_slides[:10])
        ]
        lines.append("Topics (slide titles): " + ", ".join(slide_titles))

    feedback_text = meta.get("feedback", {})
    if isinstance(feedback_text, dict):
        general = feedback_text.get("general_feedback")
        if general:
            lines.append(f"Student feedback: {general}")

    return "\n".join(lines)


async def generate_run_summary(
    db: DBSession,
    session: SessionModel,
    session_run: SessionRun,
    slides_details: list,
    user_id,
    avatar_id=None,
) -> Optional[str]:
    """
    Generate an AI summary for a completed session run and persist it.
    Does not create personal memories; the durable memory worker owns that.
    Returns the plain-text summary string.

    Idempotent: if ai_summary is already set (e.g. from a duplicate stop
    request), returns the existing summary without calling the LLM again
    or writing additional UserMemory rows.
    """
    try:
        # Re-fetch the run inside the task so we see any commit from a
        # concurrent call that beat us here.
        db.refresh(session_run)
        if session_run.ai_summary:
            logger.info(
                f"Summary already exists for run {session_run.session_run_id}, skipping"
            )
            return session_run.ai_summary

        from app.database.models import Avatar
        from app.services.memory_service import allowed
        from app.services.profession_profiles import resolve_avatar_profession

        avatar = db.get(Avatar, avatar_id) if avatar_id else None
        if (
            avatar
            and resolve_avatar_profession(avatar) == "healthcare"
            and not allowed(db, user_id, avatar, session_run)
        ):
            return None

        prompt = _build_input_prompt(session, session_run, slides_details)
        result = await _call_llm(prompt)
        if not result:
            return None

        summary_text: str = result.get("summary", "")
        memory_signals: list = result.get("memory_signals", [])

        # Persist summary on the run
        session_run.ai_summary = summary_text
        session_run.updated_at = datetime.utcnow()

        # Only the evidence-backed memory service may create persistent memories.
        db.commit()
        logger.info(
            f"Summary generated for run {session_run.session_run_id}: {len(memory_signals)} memories extracted"
        )
        return summary_text

    except Exception as e:
        logger.error(f"generate_run_summary failed: {e}")
        return None


def get_recent_session_summary(
    db: DBSession,
    session_id_str: str,
    exclude_run_id: Optional[str] = None,
    user_id=None,
) -> Optional[str]:
    """
    Return the most recent completed run's summary for a given session.
    Used to inject context into the next run.

    Pass user_id whenever the summary goes into a member's own run, so only
    that person's earlier runs are used; without it, any member's summary of
    a shared session would reach the next member. The publisher chat omits it
    on purpose (the creator reviewing their own session).
    """
    # Legacy API retained for callers; cross-session personal context now comes
    # exclusively from structured, consent-gated, individually deletable memories.
    return None


def get_user_memories(
    db: DBSession,
    user_id,
    avatar_id=None,
    limit: int = 10,
) -> list[str]:
    """
    Retrieve only active, consent-gated, unexpired memories for one twin.
    """
    from app.services.memory_service import context_memories

    return context_memories(db, user_id, avatar_id, limit)


def get_run_context(
    db: DBSession,
    session_id_str: str,
    session_run,
    avatar_id=None,
    guest_user_uuid: Optional[str] = None,
) -> tuple[Optional[str], list[str]]:
    """
    Controlled personal memories for a member's live run (no legacy summary).

    Both belong to the person running the session (session_run.user_id), never
    to the session's owner or to another member of a shared session. Guest
    runs share one user row, so they get neither.
    """
    if guest_user_uuid and str(session_run.user_id) == str(guest_user_uuid):
        return None, []
    # Unstructured summaries can restore deleted facts and bypass item retention.
    # Reuse only the user's controllable structured memory across runs.
    summary = None
    # Without an avatar, memories from every twin would match; use none.
    memories = (
        get_user_memories(db, user_id=session_run.user_id, avatar_id=avatar_id)
        if avatar_id
        else []
    )
    return summary, memories
