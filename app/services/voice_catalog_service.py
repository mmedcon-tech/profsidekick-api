"""Voice catalog for the dual voice pipeline.

Provides the two supported TTS providers' voice lists and server-side
reachability checks, used by:
  - avatar_service.publish_avatar (provider inference for legacy configs)
  - voice_resolution_service (stale subscriber-preference detection)
  - app/api/voice/api.py (catalog + preference validation endpoints)

Backend has no other ElevenLabs integration — synthesis itself stays on the
frontend BFF (`/api/tts/elevenlabs`) with its own API key. This module makes
one narrow, read-only server-side call to ElevenLabs to validate voice ids.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ELEVENLABS_VOICES_URL = "https://api.elevenlabs.io/v1/voices"
ELEVENLABS_SUBSCRIPTION_URL = "https://api.elevenlabs.io/v1/user/subscription"

# Reasons a provider can be unavailable, surfaced to the pre-session voice
# panel so it can disable the option instead of letting the subscriber hit a
# silent failure mid-session.
UNAVAILABLE_PLATFORM_QUOTA_EXCEEDED = "platform_quota_exceeded"
UNAVAILABLE_UNREACHABLE = "unreachable"

# Below this many remaining ElevenLabs characters, treat the account as
# effectively depleted — not literally zero, since a handful of leftover
# characters still can't synthesize a real utterance.
_MIN_USABLE_CHARACTERS = 100

# OpenAI TTS has no Emirati-dialect Arabic voice (see AGENTS.md dialect note) —
# every entry here only supports "en".
OPENAI_TTS_VOICES: List[Dict[str, Any]] = [
    {"id": "alloy", "name": "Alloy", "dialects": ["en"]},
    {"id": "ash", "name": "Ash", "dialects": ["en"]},
    {"id": "ballad", "name": "Ballad", "dialects": ["en"]},
    {"id": "coral", "name": "Coral", "dialects": ["en"]},
    {"id": "echo", "name": "Echo", "dialects": ["en"]},
    {"id": "fable", "name": "Fable", "dialects": ["en"]},
    {"id": "onyx", "name": "Onyx", "dialects": ["en"]},
    {"id": "nova", "name": "Nova", "dialects": ["en"]},
    {"id": "sage", "name": "Sage", "dialects": ["en"]},
    {"id": "shimmer", "name": "Shimmer", "dialects": ["en"]},
    {"id": "verse", "name": "Verse", "dialects": ["en"]},
]
_OPENAI_VOICE_IDS = {v["id"] for v in OPENAI_TTS_VOICES}


async def list_elevenlabs_voices() -> List[Dict[str, Any]]:
    """Return the account's available ElevenLabs voices, or [] if the key is
    unset or the request fails — callers treat this as "catalog unavailable",
    not a hard error."""
    if not settings.elevenlabs_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                ELEVENLABS_VOICES_URL,
                headers={"xi-api-key": settings.elevenlabs_api_key},
            )
        if response.status_code != 200:
            logger.warning(
                "ElevenLabs voices list failed: %s %s",
                response.status_code,
                response.text,
            )
            return []
        data = response.json()
        return [
            {
                "id": v.get("voice_id"),
                "name": v.get("name"),
                "dialects": ["en", "ar"],
            }
            for v in data.get("voices", [])
        ]
    except httpx.HTTPError as exc:
        logger.warning("ElevenLabs voices list request error: %s", exc)
        return []


async def check_voice_reachable(provider: str, voice_id: Optional[str]) -> bool:
    """Lightweight reachability check used at session-start validation and to
    detect stale subscriber preferences. OpenAI has no per-voice endpoint, so
    membership in the static allowlist stands in for "reachable"."""
    if not voice_id:
        return False
    if provider == "openai":
        return voice_id in _OPENAI_VOICE_IDS
    if provider == "elevenlabs":
        if not settings.elevenlabs_api_key:
            # Can't verify without a key — assume reachable rather than
            # blocking every session on a missing backend credential.
            return True
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{ELEVENLABS_VOICES_URL}/{voice_id}",
                    headers={"xi-api-key": settings.elevenlabs_api_key},
                )
            return response.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("ElevenLabs voice reachability check error: %s", exc)
            return True
    return False


async def check_provider_availability(provider: str) -> Tuple[bool, Optional[str]]:
    """Provider-level (not voice-specific) availability check, used by the
    pre-session voice panel to disable a provider entirely before the
    subscriber can pick a voice that would fail mid-session.

    Returns (available, reason). `reason` is one of
    UNAVAILABLE_PLATFORM_QUOTA_EXCEEDED / UNAVAILABLE_UNREACHABLE when
    unavailable, else None.

    OpenAI TTS has no live dependency here (static voice allowlist), so it is
    always available. ElevenLabs is a single shared platform account — this
    checks *our* account's remaining quota via /v1/user/subscription, which
    is the same account every subscriber's synthesis call draws from. A
    depleted quota here is therefore always a platform-side issue, never an
    individual subscriber's own credit balance (that is tracked separately in
    billing_service/UsageRecord).
    """
    if provider == "openai":
        return True, None
    if provider != "elevenlabs":
        return False, UNAVAILABLE_UNREACHABLE

    if not settings.elevenlabs_api_key:
        return False, UNAVAILABLE_UNREACHABLE
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                ELEVENLABS_SUBSCRIPTION_URL,
                headers={"xi-api-key": settings.elevenlabs_api_key},
            )
        if response.status_code in (401, 429):
            return False, UNAVAILABLE_PLATFORM_QUOTA_EXCEEDED
        if response.status_code != 200:
            return False, UNAVAILABLE_UNREACHABLE

        data = response.json()
        character_limit = data.get("character_limit", 0)
        character_count = data.get("character_count", 0)
        remaining = character_limit - character_count
        # A few characters "remaining" still can't synthesize any real
        # utterance (this threshold mirrors the actual failure mode: a
        # request needing ~150+ characters gets rejected with only a
        # handful of characters left on the account).
        if remaining < _MIN_USABLE_CHARACTERS:
            return False, UNAVAILABLE_PLATFORM_QUOTA_EXCEEDED
        return True, None
    except httpx.HTTPError as exc:
        logger.warning("ElevenLabs availability check error: %s", exc)
        return False, UNAVAILABLE_UNREACHABLE


def is_known_openai_voice(voice_id: Optional[str]) -> bool:
    return bool(voice_id) and voice_id.strip().lower() in _OPENAI_VOICE_IDS


def infer_provider_from_voice(voice: Optional[str]) -> str:
    """Backward-compat inference for AvatarConfiguration rows created before
    tts_provider existed: an OpenAI-style voice name means 'openai', anything
    else (an ElevenLabs voice id) means 'elevenlabs'."""
    if voice and voice.strip().lower() in _OPENAI_VOICE_IDS:
        return "openai"
    return "elevenlabs"
