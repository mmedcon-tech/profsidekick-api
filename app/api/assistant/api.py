from typing import List, Literal, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import settings

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import get_current_user
from app.schemas.schemas import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantConversationCreate,
    AssistantConversationDetail,
    AssistantConversationListResponse,
    AssistantConversationSummary,
    AssistantMessageResponse,
)
from app.services import assistant_service

"""W7 (Phase 7): AI Navigation Assistant endpoints (R104–R107).

All three roles (admin, publisher, subscriber) have access. Each user sees
only their own conversations. context_type on the conversation record
discriminates between roles.

Routes:
  GET    /api/assistant/conversations              — list user's conversations
  POST   /api/assistant/conversations              — create conversation
  GET    /api/assistant/conversations/{id}         — get conversation + messages
  DELETE /api/assistant/conversations/{id}         — delete conversation
  GET    /api/assistant/conversations/{id}/messages — paginated message list
  POST   /api/assistant/chat                       — send message, receive AI reply
"""
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class AssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    systemPrompt: Optional[str] = None
    history: List[ChatHistoryItem] = Field(default_factory=list)


class AssistantChatResponse(BaseModel):
    reply: str


@router.post("/chat", response_model=AssistantChatResponse)
async def assistant_chat(body: AssistantChatRequest) -> AssistantChatResponse:
    """Lightweight text chat for the floating MyOS assistant (OpenAI gpt-4o-mini)."""
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured on the server",
        )

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (body.systemPrompt or "").strip()
            or "You are a helpful AI training assistant for ProfSidekick subscribers.",
        },
    ]
    for item in body.history[-8:]:
        messages.append({"role": item.role, "content": item.text})
    messages.append({"role": "user", "content": body.message.strip()})

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=400,
            temperature=0.7,
        )
        reply = (response.choices[0].message.content or "").strip()
        if not reply:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Empty model response",
            )
        return AssistantChatResponse(reply=reply)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("assistant chat failed: %s", exc)
        error_text = str(exc).lower()
        if "insufficient_quota" in error_text or "quota" in error_text:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="OpenAI quota exceeded. Please add billing/credits to the OpenAI account or use a key from an account with available quota.",
            ) from exc
        if "invalid_api_key" in error_text or "incorrect api key" in error_text:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid OpenAI API key. Please create a new key and update OPENAI_API_KEY.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reach OpenAI",
        ) from exc
def _require_any_role(current_user: User = Depends(get_current_user)) -> User:
    """All authenticated users may access the assistant."""
    if current_user.role not in ("subscriber", "publisher", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authentication required")
    return current_user


# ── Conversations ─────────────────────────────────────────────────────────────

@router.get("/conversations", response_model=AssistantConversationListResponse)
def list_conversations(
    current_user: User = Depends(_require_any_role),
    db: Session = Depends(get_db),
):
    """Return all assistant conversations for the authenticated user, newest first."""
    try:
        return assistant_service.list_conversations(user_id=current_user.id, db=db)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("list_conversations error: %s", exc)
        raise HTTPException(status_code=500, detail="Error listing conversations")


@router.post(
    "/conversations",
    response_model=AssistantConversationSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    body: AssistantConversationCreate,
    current_user: User = Depends(_require_any_role),
    db: Session = Depends(get_db),
):
    """Create a new assistant conversation without sending a message yet."""
    try:
        conv = assistant_service.create_conversation(
            user=current_user,
            title=body.title,
            db=db,
            context_type=body.context_type,
            avatar_id=body.avatar_id,
            program_id=body.program_id,
        )
        msg_count = 0
        return AssistantConversationSummary(
            id=conv.id,
            title=conv.title,
            context_type=conv.context_type,
            avatar_id=conv.avatar_id,
            program_id=conv.program_id,
            message_count=msg_count,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("create_conversation error: %s", exc)
        raise HTTPException(status_code=500, detail="Error creating conversation")


@router.get("/conversations/{conversation_id}", response_model=AssistantConversationDetail)
def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(_require_any_role),
    db: Session = Depends(get_db),
):
    """Return a single conversation with its full message history."""
    try:
        return assistant_service.get_conversation_detail(
            conversation_id=conversation_id,
            user_id=current_user.id,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_conversation error: %s", exc)
        raise HTTPException(status_code=500, detail="Error fetching conversation")


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: UUID,
    current_user: User = Depends(_require_any_role),
    db: Session = Depends(get_db),
):
    """Delete a conversation and all its messages. Returns 404 if not found or not owned."""
    try:
        assistant_service.delete_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("delete_conversation error: %s", exc)
        raise HTTPException(status_code=500, detail="Error deleting conversation")


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[AssistantMessageResponse],
)
def list_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(_require_any_role),
    db: Session = Depends(get_db),
):
    """Return paginated messages for a conversation, oldest first."""
    try:
        return assistant_service.list_messages(
            conversation_id=conversation_id,
            user_id=current_user.id,
            db=db,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("list_messages error: %s", exc)
        raise HTTPException(status_code=500, detail="Error fetching messages")

