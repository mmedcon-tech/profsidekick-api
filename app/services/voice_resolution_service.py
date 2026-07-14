"""Resolves which TTS voice/provider a session should use.

Publisher-only: the avatar's publisher-configured AvatarConfiguration is the
sole source of truth. There is no subscriber-level override (removed — every
avatar's voice is decided by its publisher).
"""

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status

from app.database.models import Avatar
from app.services import voice_catalog_service


@dataclass
class VoiceResolution:
    provider: str  # 'openai' | 'elevenlabs'
    voice_id: str
    dialect: Optional[str]
    source: str  # always 'publisher'


async def resolve_session_voice(avatar: Avatar) -> VoiceResolution:
    """Resolve the effective voice for a session with `avatar` — always the
    publisher's configured voice."""
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
