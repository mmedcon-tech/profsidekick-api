"""
Session Summarization Service.

Called at session run end (stop_session_run) to generate a structured summary.
The summary is stored in SessionRun.ai_summary and is injected into future
sessions for the same user+avatar via the context builder.

For realtime voice sessions, the transcript is not yet stored in the DB,
so the summary is generated from available metadata:
  - session duration
  - slide count and titles
  - role used
  - any metadata passed by the frontend (slides_completed, etc.)

When transcript storage is implemented (Phase 6), this service can be updated
to summarize the actual conversation.

Long-term memory is also extracted here and stored in user_memories.
"""

from __future__ import annotations

import json
import uuid
import logging
from datetime import datetime
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.database.models import SessionRun, UserMemory
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
            model="gpt-4o-mini",
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
        duration_mins = int((session_run.end_time - session_run.start_time).total_seconds() / 60)

    meta = session_run.session_run_metadata or {}
    slides_completed = meta.get("slides_completed")
    student_slides = [s for s in slides_details if s.get("source") != "solution"]

    lines = [
        f"Session class: {session.class_name or 'Unknown'}",
        f"Duration: {duration_mins} minutes" if duration_mins else "Duration: unknown",
        f"Role used: {session_run.role_at_start or 'Not specified'}",
        f"Total slides: {len(student_slides)}",
        f"Slides completed: {slides_completed}" if slides_completed else "Slides completed: unknown",
    ]

    if student_slides:
        slide_titles = [s.get("title", f"Slide {s.get('slideNumber', i+1)}")
                        for i, s in enumerate(student_slides[:10])]
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
    Also extracts memory signals and stores them in user_memories.
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

        prompt = _build_input_prompt(session, session_run, slides_details)
        result = await _call_llm(prompt)
        if not result:
            return None

        summary_text: str = result.get("summary", "")
        memory_signals: list = result.get("memory_signals", [])

        # Persist summary on the run
        session_run.ai_summary = summary_text
        session_run.updated_at = datetime.utcnow()

        # Persist memory signals
        for signal in memory_signals:
            if signal and signal.strip():
                mem = UserMemory(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    avatar_id=avatar_id,
                    content=signal.strip(),
                    importance=1.0,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                db.add(mem)

        db.commit()
        logger.info(f"Summary generated for run {session_run.session_run_id}: {len(memory_signals)} memories extracted")
        return summary_text

    except Exception as e:
        logger.error(f"generate_run_summary failed: {e}")
        return None


def get_recent_session_summary(
    db: DBSession,
    session_id_str: str,
    exclude_run_id: Optional[str] = None,
) -> Optional[str]:
    """
    Return the most recent completed run's summary for a given session.
    Used to inject context into the next run.
    """
    try:
        session = db.query(SessionModel).filter(SessionModel.session_id == session_id_str).first()
        if not session:
            return None

        runs = sorted(
            [r for r in session.session_runs
             if r.ai_summary and (exclude_run_id is None or r.session_run_id != exclude_run_id)],
            key=lambda r: r.start_time or datetime.min,
            reverse=True,
        )
        return runs[0].ai_summary if runs else None
    except Exception:
        return None


def get_user_memories(
    db: DBSession,
    user_id,
    avatar_id=None,
    limit: int = 10,
) -> list[str]:
    """
    Retrieve the most recent/important memory signals for a user.
    Future: replace with vector similarity search when pgvector is active.
    """
    try:
        q = db.query(UserMemory).filter(UserMemory.user_id == user_id)
        if avatar_id:
            q = q.filter(UserMemory.avatar_id == avatar_id)
        memories = (
            q.order_by(UserMemory.importance.desc(), UserMemory.updated_at.desc())
            .limit(limit)
            .all()
        )
        return [m.content for m in memories]
    except Exception:
        return []
