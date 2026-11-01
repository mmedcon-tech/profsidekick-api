"""
POST /api/voices/authorize: may the signed-in user speak with this voice?

Used by the frontend /api/tts/elevenlabs route before it spends ElevenLabs
credits. Allowed: no voice_id (the default voice), ElevenLabs stock
("premade") voices, and clones this API created for avatars the user can
access (owner, admin, active subscriber, or a published avatar).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import AvatarConfiguration, AvatarSubscription, User
from app.dependencies.auth import get_current_user
from app.services import voice_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voices", tags=["voices"])

STOCK_CATEGORIES = {"premade"}


class VoiceAuthorizeRequest(BaseModel):
    voice_id: Optional[str] = Field(None, max_length=100)


def _can_access_avatar(db: Session, user: User, config: AvatarConfiguration) -> bool:
    avatar = config.avatar
    if avatar is None:
        return False
    if user.role == "admin" or avatar.publisher_id == user.id or avatar.is_published:
        return True
    return (
        db.query(AvatarSubscription)
        .filter(
            AvatarSubscription.subscriber_id == user.id,
            AvatarSubscription.avatar_id == avatar.id,
            AvatarSubscription.is_active.is_(True),
        )
        .first()
        is not None
    )


@router.post("/authorize")
async def authorize_voice(
    body: VoiceAuthorizeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    voice_id = (body.voice_id or "").strip()
    if not voice_id:
        return {"allowed": True, "reason": "default"}

    configs = (
        db.query(AvatarConfiguration)
        .filter(AvatarConfiguration.elevenlabs_voice_id == voice_id)
        .all()
    )
    if any(_can_access_avatar(db, current_user, c) for c in configs):
        return {"allowed": True, "reason": "avatar"}
    if configs:
        # A clone made here for an avatar this user cannot access.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Voice not allowed"
        )

    category = await voice_service.get_voice_category(voice_id)
    if category in STOCK_CATEGORIES:
        return {"allowed": True, "reason": "stock"}
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Voice not allowed"
    )
