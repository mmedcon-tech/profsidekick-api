"""W7 (Phase 7): AI Navigation Assistant service (R104–R107).

Handles multi-role context-aware conversations for all user types.
Context assembly pulls from: user role, program memberships, enrolled courses,
subscriber progress (Wave 6), recent session summaries, and UserMemory entries.
AI backend: OpenAI Chat Completions (gpt-4o).
"""

import logging
import uuid
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from openai import AsyncOpenAI
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.database.models import (
    AssistantConversation,
    AssistantMessage,
    ProgramMembership,
    AvatarSubscription,
    CourseStudent,
    UserMemory,
)
from app.database.models.progress import SubscriberCourseProgress

logger = logging.getLogger(__name__)
_openai = AsyncOpenAI(api_key=settings.openai_api_key)

_SYSTEM_PROMPT_TEMPLATE = """You are a personalized AI navigation assistant for the ProfSidekick platform.
Your role is to help the user navigate their learning journey, understand their progress,
and recommend next steps based on their context.

User context:
{context_block}

Guidelines:
- Be concise and actionable.
- Ground recommendations in the user's actual courses, progress, and program context.
- Do not reveal internal system details or other users' data.
- If asked about something outside your context, say so clearly rather than guessing."""

_MAX_HISTORY_TURNS = 20


def _build_context_block(user, db: DBSession) -> str:
    """Assemble a plain-text context block for the system prompt."""
    parts = [f"Role: {user.role}", f"Name: {user.first_name or 'User'}"]

    # Program memberships
    memberships = (
        db.query(ProgramMembership)
        .filter(ProgramMembership.user_id == user.id)
        .all()
    )
    if memberships:
        parts.append(f"Program memberships: {len(memberships)} program(s)")

    # Subscriptions (for subscribers and publishers who also subscribe)
    subscriptions = (
        db.query(AvatarSubscription)
        .filter(
            AvatarSubscription.subscriber_id == user.id,
            AvatarSubscription.is_active == True,  # noqa: E712
        )
        .all()
    )
    if subscriptions:
        parts.append(f"Active avatar subscriptions: {len(subscriptions)}")

    # Course enrollment (subscriber)
    if user.role in ("subscriber",):
        enrollments = (
            db.query(CourseStudent)
            .filter(CourseStudent.user_id == user.id)
            .all()
        )
        if enrollments:
            parts.append(f"Enrolled courses: {len(enrollments)}")

        # Progress summary (Wave 6)
        progress_rows = (
            db.query(SubscriberCourseProgress)
            .filter(SubscriberCourseProgress.user_id == user.id)
            .all()
        )
        if progress_rows:
            avg_pct = sum(p.completion_pct for p in progress_rows) / len(progress_rows)
            parts.append(f"Average course completion: {avg_pct:.1f}%")

    # Recent user memories
    memories = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == user.id)
        .order_by(UserMemory.created_at.desc())
        .limit(5)
        .all()
    )
    if memories:
        memory_lines = [m.content[:200] for m in memories if m.content]
        parts.append("Recent notes:\n" + "\n".join(f"- {line}" for line in memory_lines))

    return "\n".join(parts)


def _resolve_context_type(user) -> str:
    if user.role == "admin":
        return "admin"
    if user.role == "publisher":
        return "publisher"
    return "subscriber"


# ── Conversation CRUD ─────────────────────────────────────────────────────────

def get_conversation_or_404(conversation_id: UUID, user_id: UUID, db: DBSession) -> AssistantConversation:
    conv = (
        db.query(AssistantConversation)
        .filter(
            AssistantConversation.id == conversation_id,
            AssistantConversation.user_id == user_id,
        )
        .first()
    )
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conv


def list_conversations(user_id: UUID, db: DBSession) -> dict:
    convs = (
        db.query(AssistantConversation)
        .filter(AssistantConversation.user_id == user_id)
        .order_by(AssistantConversation.updated_at.desc())
        .all()
    )
    summaries = []
    for c in convs:
        msg_count = (
            db.query(AssistantMessage)
            .filter(AssistantMessage.conversation_id == c.id)
            .count()
        )
        summaries.append({
            "id": c.id,
            "title": c.title,
            "context_type": c.context_type,
            "avatar_id": c.avatar_id,
            "program_id": c.program_id,
            "message_count": msg_count,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        })
    return {"conversations": summaries, "total": len(summaries)}


def create_conversation(
    user,
    title: str,
    db: DBSession,
    context_type: Optional[str] = None,
    avatar_id: Optional[UUID] = None,
    program_id: Optional[UUID] = None,
) -> AssistantConversation:
    resolved_type = context_type if context_type and context_type != "auto" else _resolve_context_type(user)
    conv = AssistantConversation(
        id=uuid.uuid4(),
        user_id=user.id,
        avatar_id=avatar_id,
        program_id=program_id,
        context_type=resolved_type,
        title=title[:255],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def get_conversation_detail(conversation_id: UUID, user_id: UUID, db: DBSession) -> dict:
    conv = get_conversation_or_404(conversation_id, user_id, db)
    messages = (
        db.query(AssistantMessage)
        .filter(AssistantMessage.conversation_id == conv.id)
        .order_by(AssistantMessage.created_at)
        .all()
    )
    return {
        "id": conv.id,
        "title": conv.title,
        "context_type": conv.context_type,
        "avatar_id": conv.avatar_id,
        "program_id": conv.program_id,
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
            for m in messages
        ],
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
    }


def list_messages(conversation_id: UUID, user_id: UUID, db: DBSession, limit: int = 50, offset: int = 0) -> list:
    get_conversation_or_404(conversation_id, user_id, db)
    messages = (
        db.query(AssistantMessage)
        .filter(AssistantMessage.conversation_id == conversation_id)
        .order_by(AssistantMessage.created_at)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
        for m in messages
    ]


def delete_conversation(conversation_id: UUID, user_id: UUID, db: DBSession) -> None:
    conv = get_conversation_or_404(conversation_id, user_id, db)
    db.delete(conv)
    db.commit()


# ── Chat ──────────────────────────────────────────────────────────────────────

async def send_chat_message(
    user,
    message: str,
    db: DBSession,
    conversation_id: Optional[UUID] = None,
    avatar_id: Optional[UUID] = None,
    program_id: Optional[UUID] = None,
) -> dict:
    """Send a user message, assemble context, call GPT-4o, store both turns.

    Creates a new conversation if conversation_id is not supplied.
    Returns conversation_id, message_id, reply text, turn_number, created_at.
    """
    if conversation_id:
        conv = get_conversation_or_404(conversation_id, user.id, db)
    else:
        title_words = message.strip().split()
        auto_title = " ".join(title_words[:8])[:255] or "New conversation"
        conv = AssistantConversation(
            id=uuid.uuid4(),
            user_id=user.id,
            avatar_id=avatar_id,
            program_id=program_id,
            context_type=_resolve_context_type(user),
            title=auto_title,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(conv)
        db.flush()

    # Assemble system prompt with live context
    context_block = _build_context_block(user, db)
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(context_block=context_block)

    # Rolling conversation history (last N turns)
    existing = (
        db.query(AssistantMessage)
        .filter(AssistantMessage.conversation_id == conv.id)
        .order_by(AssistantMessage.created_at)
        .all()
    )
    history = [
        {"role": m.role, "content": m.content}
        for m in existing[-_MAX_HISTORY_TURNS:]
        if m.role in ("user", "assistant")
    ]
    turn_number = sum(1 for m in existing if m.role == "user") + 1

    # Call LLM
    try:
        oai_messages = [{"role": "system", "content": system_prompt}]
        oai_messages.extend(history)
        oai_messages.append({"role": "user", "content": message})

        response = await _openai.chat.completions.create(
            model="gpt-4o",
            messages=oai_messages,
            max_tokens=1000,
            temperature=0.7,
        )
        reply = response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("assistant_service: OpenAI call failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI assistant temporarily unavailable. Please try again.",
        )

    # Persist user turn
    user_msg = AssistantMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        role="user",
        content=message,
        created_at=datetime.utcnow(),
    )
    db.add(user_msg)

    # Persist assistant reply
    assistant_msg = AssistantMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        role="assistant",
        content=reply,
        created_at=datetime.utcnow(),
    )
    db.add(assistant_msg)

    conv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(assistant_msg)

    return {
        "conversation_id": conv.id,
        "message_id": assistant_msg.id,
        "reply": reply,
        "turn_number": turn_number,
        "created_at": assistant_msg.created_at,
    }
