"""
Subscriber Chat API

Routes:
  POST  /api/subscriber/chat/message                           — send a message, get AI reply
  GET   /api/subscriber/chat/session-run/{session_run_id}/messages — get history

RBAC: all routes require require_subscriber.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import require_subscriber
from app.schemas.schemas import SubscriberChatMessageRequest, SubscriberChatHistoryResponse, SubscriberChatMessage
from app.services import subscriber_chat_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscriber", tags=["subscriber-chat"])


@router.post("/chat/message")
async def send_chat_message(
    payload: SubscriberChatMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_subscriber),
):
    """Send one subscriber message and receive the AI teaching reply."""
    reply = await subscriber_chat_service.send_message(
        db=db,
        session_run_id=payload.session_run_id,
        subscriber_id=current_user.id,
        user_message=payload.message,
    )
    return {"reply": reply}


@router.get("/chat/session-run/{session_run_id}/messages", response_model=SubscriberChatHistoryResponse)
async def get_chat_history(
    session_run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_subscriber),
):
    """Return the full chat history for a subscriber session run."""
    messages = await subscriber_chat_service.get_history(
        db=db,
        session_run_id=session_run_id,
        subscriber_id=current_user.id,
    )
    parsed = [SubscriberChatMessage(**m) for m in messages]
    return SubscriberChatHistoryResponse(
        session_run_id=session_run_id,
        messages=parsed,
        total=len(parsed),
    )
