"""Unit tests for avatar_service.publish_avatar's voice-config validation
(dual voice pipeline — Pipeline A hardening). All DB interaction is mocked."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.avatar_service import AvatarService


def _make_avatar(publisher_id, configuration=None):
    avatar = MagicMock()
    avatar.publisher_id = publisher_id
    avatar.configuration = configuration
    return avatar


def _make_configuration(voice=None, tts_provider=None):
    config = MagicMock()
    config.voice = voice
    config.tts_provider = tts_provider
    return config


@pytest.mark.asyncio
async def test_publish_avatar_requires_configuration():
    service = AvatarService()
    publisher_id = uuid.uuid4()
    avatar = _make_avatar(publisher_id, configuration=None)

    with patch.object(AvatarService, "_load_one", return_value=avatar):
        with pytest.raises(HTTPException) as exc_info:
            await service.publish_avatar(MagicMock(), uuid.uuid4(), publisher_id)
    assert exc_info.value.status_code == 400
    assert "configuration" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_publish_avatar_requires_voice():
    service = AvatarService()
    publisher_id = uuid.uuid4()
    config = _make_configuration(voice=None)
    avatar = _make_avatar(publisher_id, configuration=config)

    with patch.object(AvatarService, "_load_one", return_value=avatar):
        with pytest.raises(HTTPException) as exc_info:
            await service.publish_avatar(MagicMock(), uuid.uuid4(), publisher_id)
    assert exc_info.value.status_code == 400
    assert "voice" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_publish_avatar_backfills_tts_provider_when_unset():
    service = AvatarService()
    publisher_id = uuid.uuid4()
    config = _make_configuration(voice="alloy", tts_provider=None)
    avatar = _make_avatar(publisher_id, configuration=config)
    db = MagicMock()

    with patch.object(AvatarService, "_load_one", return_value=avatar):
        result = await service.publish_avatar(db, uuid.uuid4(), publisher_id)

    assert config.tts_provider == "openai"  # inferred from the "alloy" voice name
    assert avatar.is_published is True
    assert result is avatar
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_publish_avatar_backfills_elevenlabs_for_non_openai_voice():
    service = AvatarService()
    publisher_id = uuid.uuid4()
    config = _make_configuration(voice="rachel", tts_provider=None)
    avatar = _make_avatar(publisher_id, configuration=config)

    with patch.object(AvatarService, "_load_one", return_value=avatar):
        await service.publish_avatar(MagicMock(), uuid.uuid4(), publisher_id)

    assert config.tts_provider == "elevenlabs"


@pytest.mark.asyncio
async def test_publish_avatar_does_not_overwrite_existing_tts_provider():
    service = AvatarService()
    publisher_id = uuid.uuid4()
    config = _make_configuration(voice="alloy", tts_provider="elevenlabs")
    avatar = _make_avatar(publisher_id, configuration=config)

    with patch.object(AvatarService, "_load_one", return_value=avatar):
        await service.publish_avatar(MagicMock(), uuid.uuid4(), publisher_id)

    assert (
        config.tts_provider == "elevenlabs"
    )  # unchanged — publisher's explicit choice wins
