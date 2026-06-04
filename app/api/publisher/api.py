"""
Publisher Learning System — API layer.

Routes:
  POST   /api/publisher/chat
  GET    /api/publisher/conversations
  GET    /api/publisher/conversations/{id}
  DELETE /api/publisher/conversations/{id}
  POST   /api/publisher/feedback
  GET    /api/publisher/preferences
  PUT    /api/publisher/preferences

RBAC: all routes require require_publisher (publisher or admin).
Ownership: publishers see only their own data; admin access to all
           is addable later via separate admin routes.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import require_publisher
from app.schemas.schemas import (
    ChatRequest,
    ChatResponse,
    ChatOptionsRequest,
    ChatOptionsResponse,
    ChatSelectRequest,
    ChatSelectResponse,
    ChatStartRequest,
    ChatStartResponse,
    ConversationDetail,
    ConversationListResponse,
    ResponseEditCreate,
    ResponseEditResponse,
    PreferenceUpsert,
    PreferenceResponse,
    PreferenceListResponse,
)
from app.services.publisher_chat_service import (
    publisher_chat_service,
    preference_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/publisher", tags=["publisher-learning"])


# ─── Chat Start (AI speaks first) ────────────────────────────────────────────

@router.post("/chat/start", response_model=ChatStartResponse, status_code=status.HTTP_201_CREATED)
async def start_chat(
    request: ChatStartRequest,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Begin a new conversation where the AI sends the first message.

    Creates a new conversation, assembles the full system prompt (template prompt,
    role context, rubric, knowledge, slides, publisher preferences + feedback notes),
    and calls the LLM with a session-start trigger so the AI opens the session.

    Returns the conversation_id and the AI's opening message.
    """
    try:
        result = await publisher_chat_service.start_conversation(db, current_user.id, request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ start_chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Session start failed: {e}")


# ─── Chat ────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Send a message in a publisher chat session.

    - Pass conversation_id to continue an existing conversation.
    - Omit conversation_id to start a new one (title auto-generated from first message).
    - Optionally pass avatar_id to ground the AI in that avatar's configuration.
    - Optionally pass preferences dict to override publisher-level settings for this turn.

    Ownership: the resolved conversation must belong to the calling publisher.
    """
    try:
        result = await publisher_chat_service.chat(db, current_user.id, request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ publisher chat error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat failed: {e}",
        )


@router.post("/chat/options", response_model=ChatOptionsResponse)
async def generate_options(
    request: ChatOptionsRequest,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Generate N independent AI responses for the same prompt.

    Calls gpt-4o N times in parallel (temperatures 0.7 / 0.85 / 1.0 …)
    to produce meaningfully different phrasings.

    Nothing is stored yet. The publisher calls POST /chat/select to
    commit the chosen option and record the preference.
    """
    try:
        result = await publisher_chat_service.generate_options(db, current_user.id, request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ generate_options error: {e}")
        raise HTTPException(status_code=500, detail=f"Option generation failed: {e}")


@router.post("/chat/select", response_model=ChatSelectResponse, status_code=status.HTTP_201_CREATED)
async def select_option(
    request: ChatSelectRequest,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Commit a publisher-chosen option to conversation history and record feedback.

    Writes:
      - publisher_messages: user turn + selected assistant turn
      - feedback_preferences: selected_response + rejected_responses
    """
    try:
        result = await publisher_chat_service.commit_selection(
            db, current_user.id, request
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ select_option error: {e}")
        raise HTTPException(status_code=500, detail=f"Option selection failed: {e}")


# ─── Conversations ────────────────────────────────────────────────────────────

@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """Return all conversations for the authenticated publisher, newest first."""
    try:
        return publisher_chat_service.list_conversations(db, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ list_conversations error: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing conversations: {e}")


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Return a single conversation with its full message history.
    Returns 404 if the conversation does not exist or belongs to another publisher.
    """
    try:
        return publisher_chat_service.get_conversation(db, current_user.id, conversation_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ get_conversation error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching conversation: {e}")


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Delete a conversation and all its messages.
    Returns 404 if not found or not owned by the calling publisher.
    """
    try:
        publisher_chat_service.delete_conversation(db, current_user.id, conversation_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ delete_conversation error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting conversation: {e}")


# ─── Editable AI Responses ────────────────────────────────────────────────────

@router.post(
    "/messages/{message_id}/edit",
    response_model=ResponseEditResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_response_edit(
    message_id: UUID,
    data: ResponseEditCreate,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Save a publisher's inline edit to an AI-generated response.

    Stores: original_content, edited_content, session_id, avatar_id, timestamp.
    Flagged as 'publisher_refinement' for future teaching-style analysis.
    Does NOT modify the stored conversation message — only records the edit.
    """
    try:
        row = publisher_chat_service.save_response_edit(
            db, current_user.id, message_id, data
        )
        return row
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ save_response_edit error: {e}")
        raise HTTPException(status_code=500, detail=f"Edit save failed: {e}")


# ─── Preferences ──────────────────────────────────────────────────────────────

@router.get("/preferences", response_model=PreferenceListResponse)
def list_preferences(
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Return all stored preferences for the authenticated publisher.

    Built-in keys (examples):
      preferred_difficulty  → "beginner" | "intermediate" | "advanced"
      feedback_style        → "socratic" | "direct" | "encouraging"
      question_style        → "conceptual" | "applied" | "mixed"
      grading_strictness    → "lenient" | "standard" | "strict"
    """
    try:
        rows = preference_service.list(db, current_user.id)
        return {"preferences": rows}
    except Exception as e:
        logger.error(f"❌ list_preferences error: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing preferences: {e}")


@router.put("/preferences", response_model=PreferenceResponse)
def upsert_preference(
    data: PreferenceUpsert,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Create or update a publisher preference by key.
    If the key already exists, its value is overwritten.
    value accepts any JSON-serialisable type (string, number, boolean, object).
    """
    try:
        row = preference_service.upsert(db, current_user.id, data.key, data.value)
        return row
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ upsert_preference error: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving preference: {e}")
