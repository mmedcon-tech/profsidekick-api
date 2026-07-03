"""Unit tests for voice_resolution_service — all DB interaction is mocked."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.voice_resolution_service import (
    resolve_session_voice,
    validate_and_clear_stale_preference,
)


def _make_preference(
    provider="elevenlabs", voice_id="rachel", dialect="en-US", is_valid=True
):
    pref = MagicMock()
    pref.provider = provider
    pref.voice_id = voice_id
    pref.dialect = dialect
    pref.is_valid = is_valid
    return pref


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


def _db_with_preference(preference):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = preference
    return db


@pytest.mark.asyncio
async def test_subscriber_preference_takes_priority_over_publisher_default():
    db = _db_with_preference(_make_preference())
    avatar = _make_avatar()
    user = MagicMock(id=uuid.uuid4())

    result = await resolve_session_voice(db, avatar, user)

    assert result.source == "subscriber"
    assert result.provider == "elevenlabs"
    assert result.voice_id == "rachel"


@pytest.mark.asyncio
async def test_falls_back_to_publisher_default_when_no_preference():
    db = _db_with_preference(None)
    avatar = _make_avatar(voice="alloy", tts_provider="openai")
    user = MagicMock(id=uuid.uuid4())

    result = await resolve_session_voice(db, avatar, user)

    assert result.source == "publisher"
    assert result.provider == "openai"
    assert result.voice_id == "alloy"


@pytest.mark.asyncio
async def test_infers_provider_when_avatar_config_has_no_tts_provider():
    db = _db_with_preference(None)
    avatar = _make_avatar(voice="rachel", tts_provider=None)
    user = MagicMock(id=uuid.uuid4())

    result = await resolve_session_voice(db, avatar, user)

    assert (
        result.provider == "elevenlabs"
    )  # inferred: "rachel" isn't an OpenAI voice name


@pytest.mark.asyncio
async def test_raises_when_avatar_has_no_usable_configuration():
    db = _db_with_preference(None)
    avatar = _make_avatar(has_config=False)
    user = MagicMock(id=uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await resolve_session_voice(db, avatar, user)
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_stale_preference_is_cleared_and_falls_back_when_validated():
    preference = _make_preference(provider="elevenlabs", voice_id="deleted-voice")
    db = _db_with_preference(preference)
    avatar = _make_avatar(voice="alloy", tts_provider="openai")
    user = MagicMock(id=uuid.uuid4())

    with patch(
        "app.services.voice_catalog_service.check_voice_reachable",
        new=AsyncMock(return_value=False),
    ):
        result = await resolve_session_voice(
            db, avatar, user, validate_reachability=True
        )

    assert preference.is_valid is False
    assert preference.voice_id is None
    assert result.source == "publisher"
    assert result.provider == "openai"


@pytest.mark.asyncio
async def test_validate_and_clear_stale_preference_returns_true_when_reachable():
    preference = _make_preference()
    db = MagicMock()

    with patch(
        "app.services.voice_catalog_service.check_voice_reachable",
        new=AsyncMock(return_value=True),
    ):
        still_valid = await validate_and_clear_stale_preference(db, preference)

    assert still_valid is True
    assert preference.is_valid is True
    db.commit.assert_not_called()
