"""
Subscriber Chat Service

Provides text-based chat sessions for subscribers in sessions configured with
subscriber_runtime_mode = 'chat' or when a subscriber selects 'chat' in 'choice' mode.

Conversation history is stored in session_run.session_run_metadata under
the key 'chat_messages' as a list of {role, content, id, created_at} dicts.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from openai import AsyncOpenAI
from fastapi import HTTPException, status

from app.config import settings
from app.database.models import (
    Session as SessionModel,
    SessionRun,
    SessionRunStatus,
    Avatar,
    AvatarConfiguration,
    AvatarTemplate,
    AvatarTemplateVersion,
)
from app.services.context_builder import build_chat_system_prompt

_openai = AsyncOpenAI(api_key=settings.openai_api_key)
_CHAT_MODEL = "gpt-4o"
_MAX_HISTORY = 30


def _get_session_run(db: Session, session_run_id: str) -> Optional[SessionRun]:
    return db.query(SessionRun).filter(SessionRun.session_run_id == session_run_id).first()


def _get_history(run: SessionRun) -> List[Dict[str, Any]]:
    meta = run.session_run_metadata or {}
    return list(meta.get("chat_messages", []))


def _save_history(db: Session, run: SessionRun, messages: List[Dict[str, Any]]) -> None:
    meta = dict(run.session_run_metadata or {})
    meta["chat_messages"] = messages
    run.session_run_metadata = meta
    db.commit()


def _openai_messages(history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    tail = history[-_MAX_HISTORY:]
    return [{"role": m["role"], "content": m["content"]} for m in tail]


def _resolve_avatar_context(db: Session, db_session: SessionModel) -> Dict[str, Any]:
    """Extract all avatar-related prompt fields from the session's avatar."""
    ctx: Dict[str, Any] = {
        "avatar_name": "AI Teaching Assistant",
        "conversation_prompt": None,
        "teaching_prompt": None,
        "examination_prompt": None,
        "refined_prompt": None,
        "difficulty_level": None,
        "rubrics": [],
        "knowledge_chunks": [],
        "reference_solutions": [],
    }
    if not db_session.avatar_id:
        return ctx

    avatar: Optional[Avatar] = db.query(Avatar).filter(Avatar.id == db_session.avatar_id).first()
    if not avatar:
        return ctx

    ctx["avatar_name"] = avatar.name

    # Resolve profile refined_prompt
    if avatar.profile and avatar.profile.refined_prompt:
        ctx["refined_prompt"] = avatar.profile.refined_prompt.strip() or None

    # Resolve template version prompts
    version: Optional[AvatarTemplateVersion] = (
        avatar.template_version
        or (avatar.template.current_version if avatar.template else None)
    )
    if version:
        ctx["conversation_prompt"] = (version.conversation_prompt or "").strip() or None
        ctx["teaching_prompt"] = (getattr(version, "teaching_prompt", None) or "").strip() or None
        ctx["examination_prompt"] = (getattr(version, "examination_prompt", None) or "").strip() or None
    elif avatar.template and avatar.template.hidden_system_prompt:
        ctx["conversation_prompt"] = (avatar.template.hidden_system_prompt or "").strip() or None

    # Resolve configuration: difficulty, rubrics, knowledge
    cfg: Optional[AvatarConfiguration] = avatar.configuration
    if cfg:
        ctx["difficulty_level"] = cfg.difficulty_level
        ctx["rubrics"] = list(cfg.rubrics or [])
        ctx["knowledge_chunks"] = [
            d.content_text for d in (cfg.knowledge_documents or []) if d.content_text
        ]
        ctx["reference_solutions"] = [
            s.content_text for s in (cfg.reference_solutions or []) if s.content_text
        ]

    return ctx


def _student_slides(db_session: SessionModel) -> List[Dict[str, Any]]:
    slides = db_session.slides_details or []
    return [s for s in slides if s.get("source") != "solution"]


async def get_history(db: Session, session_run_id: str, subscriber_id: Any) -> List[Dict[str, Any]]:
    run = _get_session_run(db, session_run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found.")
    if str(run.user_id) != str(subscriber_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your session run.")
    return _get_history(run)


async def send_message(
    db: Session,
    session_run_id: str,
    subscriber_id: Any,
    user_message: str,
) -> str:
    """Process one subscriber message and return the AI reply."""
    run = _get_session_run(db, session_run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found.")
    if str(run.user_id) != str(subscriber_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your session run.")
    if run.status != SessionRunStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session run is not active.")

    runtime = getattr(run, "runtime_mode_used", None)
    if runtime and runtime != "chat":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This session run was started in avatar mode, not chat mode.",
        )

    parent = db.query(SessionModel).filter(SessionModel.id == run.session_id).first()
    if not parent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent session not found.")

    session_mode = getattr(parent, "session_mode", "teaching") or "teaching"
    slides = _student_slides(parent)
    av_ctx = _resolve_avatar_context(db, parent)

    system_prompt = build_chat_system_prompt(
        avatar_name=av_ctx["avatar_name"],
        conversation_prompt=av_ctx["conversation_prompt"],
        teaching_prompt=av_ctx["teaching_prompt"],
        examination_prompt=av_ctx["examination_prompt"],
        refined_prompt=av_ctx["refined_prompt"],
        session_mode=session_mode,
        difficulty_level=av_ctx["difficulty_level"],
        rubrics=av_ctx["rubrics"],
        knowledge_chunks=av_ctx["knowledge_chunks"],
        reference_solutions=av_ctx["reference_solutions"],
        session_slides=slides,
        preferences={},
    )

    history = _get_history(run)
    openai_messages = [{"role": "system", "content": system_prompt}]
    openai_messages += _openai_messages(history)
    openai_messages.append({"role": "user", "content": user_message})

    completion = await _openai.chat.completions.create(
        model=_CHAT_MODEL,
        messages=openai_messages,
        temperature=0.7,
    )
    reply = completion.choices[0].message.content or ""

    now = datetime.utcnow().isoformat()
    history.append({"id": str(uuid.uuid4()), "role": "user", "content": user_message, "created_at": now})
    history.append({"id": str(uuid.uuid4()), "role": "assistant", "content": reply, "created_at": now})
    _save_history(db, run, history)

    return reply
