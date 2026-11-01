"""
Avatar voice and LiveAvatar choices for the publisher's avatar settings page.

Routes:
  GET    /api/publisher/voices                          ElevenLabs voices
  GET    /api/publisher/liveavatar/avatars              LiveAvatar avatars
  POST   /api/publisher/avatars/{avatar_id}/voice-clone  create an instant clone
  DELETE /api/publisher/avatars/{avatar_id}/voice-clone  delete it

RBAC: require_publisher. Clone routes use the same ownership check as the
avatar configuration routes. Provider keys stay on the server.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database.connection import get_db
from app.database.models import AuditEvent, AvatarConfiguration, User
from app.dependencies.auth import require_publisher
from app.services import voice_service
from app.services.audit_service import record_audit_event
from app.services.avatar_service import AvatarService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/publisher", tags=["publisher-voices"])
avatar_service = AvatarService()

CLONE_CREATED = "avatar.voice_clone_created"
CLONE_DELETED = "avatar.voice_clone_deleted"


async def _owned_configuration(
    db: Session, avatar_id: UUID, user: User
) -> AvatarConfiguration:
    avatar = await avatar_service.get_avatar(db, avatar_id)
    if not avatar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found"
        )
    avatar_service._require_owner(avatar, user.id)
    if not avatar.configuration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Save the avatar's settings before adding a voice",
        )
    return avatar.configuration


def _clones_today(db: Session, user_id) -> int:
    since = datetime.utcnow() - timedelta(days=1)
    return (
        db.query(AuditEvent)
        .filter(
            AuditEvent.actor_user_id == user_id,
            AuditEvent.action == CLONE_CREATED,
            AuditEvent.created_at >= since,
        )
        .count()
    )


@router.get("/voices")
async def list_voices(
    search: Optional[str] = None,
    current_user: User = Depends(require_publisher),
):
    return await voice_service.list_elevenlabs_voices(search)


@router.get("/liveavatar/avatars")
async def list_liveavatar_avatars(current_user: User = Depends(require_publisher)):
    return await voice_service.list_liveavatar_avatars()


@router.post("/avatars/{avatar_id}/voice-clone")
async def create_voice_clone(
    avatar_id: UUID,
    name: str = Form(..., min_length=1, max_length=200),
    consent: bool = Form(False),
    remove_background_noise: bool = Form(False),
    files: List[UploadFile] = File(...),
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Create an ElevenLabs instant voice clone and make it the avatar's voice.
    The audio is streamed to ElevenLabs and not stored here.
    """
    if not consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Confirm that this is your voice or that you have the "
                "speaker's permission"
            ),
        )
    config = await _owned_configuration(db, avatar_id, current_user)
    if _clones_today(db, current_user.id) >= settings.voice_clone_daily_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Voice clone limit reached for today. Try again tomorrow.",
        )

    samples = [
        (f.filename or "sample", f.file, f.content_type or "application/octet-stream")
        for f in files
    ]
    voice_service.validate_clone_samples(samples)
    try:
        result = await voice_service.create_instant_clone(
            name.strip(), samples, remove_background_noise
        )
    finally:
        for f in files:
            await f.close()

    # A new clone replaces the avatar's previous one; do not leave the old
    # recording of someone's voice behind at ElevenLabs.
    previous_clone = (
        config.elevenlabs_voice_id if config.voice_clone_consent_at else None
    )
    now = datetime.utcnow()
    settings_json = dict(config.additional_settings or {})
    settings_json["voiceCloneRequiresVerification"] = result["requires_verification"]
    config.additional_settings = settings_json
    config.elevenlabs_voice_id = result["voice_id"]
    config.voice_clone_name = name.strip()
    config.voice_clone_consent_at = now
    # Until ElevenLabs verifies the voice, sessions keep the current voice.
    if not result["requires_verification"]:
        config.voice_provider = "elevenlabs"
    config.updated_at = now
    record_audit_event(
        db,
        action=CLONE_CREATED,
        entity_type="avatar",
        entity_id=avatar_id,
        actor_user_id=current_user.id,
        data={
            "voice_id": result["voice_id"],
            "voice_name": name.strip(),
            "consent_at": now.isoformat(),
            "sample_count": len(samples),
            "requires_verification": result["requires_verification"],
        },
    )
    db.commit()

    if previous_clone and previous_clone != result["voice_id"]:
        try:
            await voice_service.delete_elevenlabs_voice(previous_clone)
        except HTTPException:
            logger.warning(
                "Could not delete replaced voice clone for avatar %s", avatar_id
            )

    return result


@router.delete("/avatars/{avatar_id}/voice-clone")
async def delete_voice_clone(
    avatar_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """Delete the avatar's clone at ElevenLabs and clear it from the settings."""
    config = await _owned_configuration(db, avatar_id, current_user)
    # Only a clone made here (consent recorded) is deleted; never a stock voice.
    if not config.voice_clone_consent_at or not config.elevenlabs_voice_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This avatar has no voice clone",
        )

    voice_id = config.elevenlabs_voice_id
    await voice_service.delete_elevenlabs_voice(voice_id)

    config.elevenlabs_voice_id = None
    config.voice_clone_name = None
    config.voice_clone_consent_at = None
    if config.voice_provider == "elevenlabs":
        config.voice_provider = "openai"
    settings_json = dict(config.additional_settings or {})
    settings_json.pop("voiceCloneRequiresVerification", None)
    config.additional_settings = settings_json
    config.updated_at = datetime.utcnow()
    record_audit_event(
        db,
        action=CLONE_DELETED,
        entity_type="avatar",
        entity_id=avatar_id,
        actor_user_id=current_user.id,
        data={"voice_id": voice_id},
    )
    db.commit()
    return {"deleted": True}
