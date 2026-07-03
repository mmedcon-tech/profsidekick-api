"""Dual voice pipeline — resolves which TTS voice a session should use.

Priority order (Pipeline B over Pipeline A):
  1. The subscriber's saved SubscriberVoicePreference, if valid.
  2. The avatar's publisher-configured AvatarConfiguration (Pipeline A).
Raises if neither yields a usable voice — this should be prevented by the
hardened publish_avatar() validation, but the check stays defensive here
since resolve_session_voice runs on every session start.
"""

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import Avatar, SubscriberVoicePreference, User
from app.services import voice_catalog_service


@dataclass
class VoiceResolution:
    provider: str  # 'openai' | 'elevenlabs'
    voice_id: str
    dialect: Optional[str]
    source: str  # 'subscriber' | 'publisher'


async def validate_and_clear_stale_preference(
    db: Session, preference: SubscriberVoicePreference
) -> bool:
    """Checks the preference's voice against the provider; if it's no longer
    recognized, clears it (is_valid=False, voice_id=None) so the caller falls
    back to the publisher default. Returns True if the preference is (still)
    usable."""
    reachable = await voice_catalog_service.check_voice_reachable(
        preference.provider, preference.voice_id
    )
    if not reachable:
        preference.is_valid = False
        preference.voice_id = None
        db.commit()
        return False
    return True


async def resolve_session_voice(
    db: Session,
    avatar: Avatar,
    user: User,
    validate_reachability: bool = False,
) -> VoiceResolution:
    """Resolve the effective voice for `user` starting a session with `avatar`.

    `validate_reachability` triggers a live provider check (used by the
    pre-session eligibility validation, not on every ephemeral-token mint,
    since it makes an external HTTP call).
    """
    preference = (
        db.query(SubscriberVoicePreference)
        .filter(
            SubscriberVoicePreference.user_id == user.id,
            SubscriberVoicePreference.is_valid.is_(True),
        )
        .first()
    )

    if preference and preference.voice_id:
        if validate_reachability:
            still_valid = await validate_and_clear_stale_preference(db, preference)
            if not still_valid:
                preference = None

        if preference and preference.voice_id:
            return VoiceResolution(
                provider=preference.provider,
                voice_id=preference.voice_id,
                dialect=preference.dialect,
                source="subscriber",
            )

    config = avatar.configuration
    if not config or not config.voice:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="This avatar has no usable voice configuration.",
        )

    provider = config.tts_provider or voice_catalog_service.infer_provider_from_voice(
        config.voice
    )
    return VoiceResolution(
        provider=provider,
        voice_id=config.voice,
        dialect=config.language,
        source="publisher",
    )
