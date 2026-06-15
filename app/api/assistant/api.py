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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


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


# ── Chat ──────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=AssistantChatResponse)
async def chat(
    body: AssistantChatRequest,
    current_user: User = Depends(_require_any_role),
    db: Session = Depends(get_db),
):
    """Send a message to the navigation assistant and receive a context-aware reply.

    If conversation_id is omitted, a new conversation is created automatically.
    context_type is derived from the user's role.
    """
    try:
        result = await assistant_service.send_chat_message(
            user=current_user,
            message=body.message,
            db=db,
            conversation_id=body.conversation_id,
            avatar_id=body.avatar_id,
            program_id=body.program_id,
        )
        return AssistantChatResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("assistant chat error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Chat error: {exc}")
