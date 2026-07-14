"""Unit tests for voice_resolution_service — publisher-only, no subscriber
override. All DB interaction is mocked."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.voice_resolution_service import resolve_session_voice


def _make_avatar(
    voice="alloy", tts_provider="openai", language="en-US", has_config=True
):
    avatar = MagicMock()
    if has_config:
        config = MagicMock()
        config.voice = voice
        config.tts_provider = tts_provider
        config.language = language
        avatar.configuration = config
    else:
        avatar.configuration = None
    return avatar


@pytest.mark.asyncio
async def test_resolves_publisher_configured_voice():
    avatar = _make_avatar(voice="alloy", tts_provider="openai", language="en-US")

    result = await resolve_session_voice(avatar)

    assert result.source == "publisher"
    assert result.provider == "openai"
    assert result.voice_id == "alloy"
    assert result.dialect == "en-US"


@pytest.mark.asyncio
async def test_resolves_publisher_configured_elevenlabs_voice():
    avatar = _make_avatar(voice="rachel", tts_provider="elevenlabs", language="ar-AE")

    result = await resolve_session_voice(avatar)

    assert result.source == "publisher"
    assert result.provider == "elevenlabs"
    assert result.voice_id == "rachel"
    assert result.dialect == "ar-AE"


@pytest.mark.asyncio
async def test_infers_provider_when_avatar_config_has_no_tts_provider():
    avatar = _make_avatar(voice="rachel", tts_provider=None)

    result = await resolve_session_voice(avatar)

    assert (
        result.provider == "elevenlabs"
    )  # inferred: "rachel" isn't an OpenAI voice name


@pytest.mark.asyncio
async def test_raises_when_avatar_has_no_usable_configuration():
    avatar = _make_avatar(has_config=False)

    with pytest.raises(HTTPException) as exc_info:
        await resolve_session_voice(avatar)
    assert exc_info.value.status_code == 500
