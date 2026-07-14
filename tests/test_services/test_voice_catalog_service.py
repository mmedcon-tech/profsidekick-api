"""Unit tests for voice_catalog_service — all HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import voice_catalog_service


# ---------------------------------------------------------------------------
# infer_provider_from_voice
# ---------------------------------------------------------------------------


def test_infer_provider_openai_voice_name():
    assert voice_catalog_service.infer_provider_from_voice("alloy") == "openai"
    assert voice_catalog_service.infer_provider_from_voice("Nova") == "openai"


def test_infer_provider_defaults_to_elevenlabs():
    assert voice_catalog_service.infer_provider_from_voice("rachel") == "elevenlabs"
    assert voice_catalog_service.infer_provider_from_voice(None) == "elevenlabs"
    assert voice_catalog_service.infer_provider_from_voice("") == "elevenlabs"


# ---------------------------------------------------------------------------
# list_elevenlabs_voices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_elevenlabs_voices_without_api_key_returns_empty():
    with patch.object(voice_catalog_service.settings, "elevenlabs_api_key", ""):
        assert await voice_catalog_service.list_elevenlabs_voices() == []


@pytest.mark.asyncio
async def test_list_elevenlabs_voices_maps_response():
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {
        "voices": [{"voice_id": "abc123", "name": "Rachel"}]
    }
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

    with patch.object(
        voice_catalog_service.settings, "elevenlabs_api_key", "test-key"
    ), patch(
        "app.services.voice_catalog_service.httpx.AsyncClient", return_value=mock_client
    ):
        voices = await voice_catalog_service.list_elevenlabs_voices()

    assert voices == [{"id": "abc123", "name": "Rachel", "dialects": ["en", "ar"]}]


# ---------------------------------------------------------------------------
# check_provider_availability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_provider_availability_openai_always_available():
    available, reason = await voice_catalog_service.check_provider_availability(
        "openai"
    )
    assert available is True
    assert reason is None


@pytest.mark.asyncio
async def test_check_provider_availability_elevenlabs_without_api_key():
    with patch.object(voice_catalog_service.settings, "elevenlabs_api_key", ""):
        available, reason = await voice_catalog_service.check_provider_availability(
            "elevenlabs"
        )
    assert available is False
    assert reason == voice_catalog_service.UNAVAILABLE_UNREACHABLE


@pytest.mark.asyncio
async def test_check_provider_availability_elevenlabs_quota_exceeded():
    """Mirrors the real-world failure: our platform ElevenLabs account has
    run out of quota — this must classify as platform-side, never as the
    subscriber's own credit balance."""
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {
        "character_count": 9993,
        "character_limit": 10000,
    }
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

    with patch.object(
        voice_catalog_service.settings, "elevenlabs_api_key", "test-key"
    ), patch(
        "app.services.voice_catalog_service.httpx.AsyncClient", return_value=mock_client
    ):
        available, reason = await voice_catalog_service.check_provider_availability(
            "elevenlabs"
        )

    assert available is False
    assert reason == voice_catalog_service.UNAVAILABLE_PLATFORM_QUOTA_EXCEEDED


@pytest.mark.asyncio
async def test_check_provider_availability_elevenlabs_401_is_quota_exceeded():
    mock_response = MagicMock(status_code=401)
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

    with patch.object(
        voice_catalog_service.settings, "elevenlabs_api_key", "test-key"
    ), patch(
        "app.services.voice_catalog_service.httpx.AsyncClient", return_value=mock_client
    ):
        available, reason = await voice_catalog_service.check_provider_availability(
            "elevenlabs"
        )

    assert available is False
    assert reason == voice_catalog_service.UNAVAILABLE_PLATFORM_QUOTA_EXCEEDED


@pytest.mark.asyncio
async def test_check_provider_availability_elevenlabs_ok_with_remaining_quota():
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"character_count": 100, "character_limit": 10000}
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

    with patch.object(
        voice_catalog_service.settings, "elevenlabs_api_key", "test-key"
    ), patch(
        "app.services.voice_catalog_service.httpx.AsyncClient", return_value=mock_client
    ):
        available, reason = await voice_catalog_service.check_provider_availability(
            "elevenlabs"
        )

    assert available is True
    assert reason is None


@pytest.mark.asyncio
async def test_check_provider_availability_elevenlabs_request_error_is_unreachable():
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.get = AsyncMock(
        side_effect=httpx.ConnectError("boom")
    )

    with patch.object(
        voice_catalog_service.settings, "elevenlabs_api_key", "test-key"
    ), patch(
        "app.services.voice_catalog_service.httpx.AsyncClient", return_value=mock_client
    ):
        available, reason = await voice_catalog_service.check_provider_availability(
            "elevenlabs"
        )

    assert available is False
    assert reason == voice_catalog_service.UNAVAILABLE_UNREACHABLE
