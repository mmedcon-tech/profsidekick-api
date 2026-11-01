"""
Avatar voice settings: ElevenLabs instant voice clones and the LiveAvatar
avatar/voice handed to live sessions. Provider HTTP calls are faked.
Integration test: needs the test database (see tests/conftest.py).
"""

import uuid
from datetime import datetime

import httpx
import pytest

from app.api.sessions import api as sessions_api
from app.database.models import (
    AuditEvent,
    Avatar,
    AvatarConfiguration,
    AvatarTemplate,
    SessionRun,
    User,
)
from app.dependencies.auth import get_current_user, get_optional_user
from app.main import app
from app.services import voice_service

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


class _FakeClient:
    calls = []
    responses = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _reply(self, method, url, **kwargs):
        _FakeClient.calls.append((method, url, kwargs))
        status_code, payload = _FakeClient.responses.get(
            (method, url.split("api.elevenlabs.io")[-1]), (200, {})
        )
        return httpx.Response(status_code, json=payload)

    async def get(self, url, **kwargs):
        return self._reply("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        if "files" in kwargs:
            kwargs["file_names"] = [f[1][0] for f in kwargs["files"]]
        return self._reply("POST", url, **kwargs)

    async def delete(self, url, **kwargs):
        return self._reply("DELETE", url, **kwargs)


@pytest.fixture
def elevenlabs(monkeypatch):
    _FakeClient.calls = []
    _FakeClient.responses = {
        ("POST", "/v1/voices/add"): (
            200,
            {"voice_id": "clone_1", "requires_verification": False},
        ),
    }
    monkeypatch.setattr(voice_service.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(voice_service.settings, "elevenlabs_api_key", "xi_test")
    return _FakeClient


@pytest.fixture
def publisher(db_session, test_user):
    test_user.role = "publisher"
    db_session.commit()
    return test_user


@pytest.fixture
def avatar(db_session, publisher):
    template = AvatarTemplate(
        id=uuid.uuid4(), name="Twin", category="Healthcare", created_by=publisher.id
    )
    db_session.add(template)
    db_session.flush()
    row = Avatar(
        id=uuid.uuid4(),
        template_id=template.id,
        publisher_id=publisher.id,
        name="Dr Twin",
    )
    db_session.add(row)
    db_session.flush()
    db_session.add(
        AvatarConfiguration(id=uuid.uuid4(), avatar_id=row.id, voice="alloy")
    )
    db_session.commit()
    return row


def _clone(client, avatar_id, consent="true", files=None):
    return client.post(
        f"/api/publisher/avatars/{avatar_id}/voice-clone",
        data={"name": "Dr Twin voice", "consent": consent},
        files=files or [("files", ("sample.mp3", MP3, "audio/mpeg"))],
    )


def test_clone_without_consent_is_refused(client, avatar, elevenlabs):
    res = _clone(client, avatar.id, consent="false")
    assert res.status_code == 400
    assert elevenlabs.calls == []


def test_clone_by_non_owner_is_forbidden(client, db_session, avatar, elevenlabs):
    other = User(
        id=uuid.uuid4(),
        username=f"other_{uuid.uuid4().hex[:8]}",
        email=f"other_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        first_name="Other",
        last_name="Publisher",
        role="publisher",
    )
    db_session.add(other)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: other
    res = _clone(client, avatar.id)
    assert res.status_code == 403
    assert elevenlabs.calls == []


def test_clone_rejects_non_audio_files(client, avatar, elevenlabs):
    res = _clone(
        client,
        avatar.id,
        files=[("files", ("notes.mp3", b"hello world, not audio", "audio/mpeg"))],
    )
    assert res.status_code == 400
    assert elevenlabs.calls == []


def test_clone_stores_voice_and_consent(
    client, db_session, avatar, publisher, elevenlabs
):
    res = _clone(client, avatar.id)
    assert res.status_code == 200, res.text
    assert res.json() == {"voice_id": "clone_1", "requires_verification": False}

    method, url, kwargs = elevenlabs.calls[0]
    assert (method, url) == ("POST", "https://api.elevenlabs.io/v1/voices/add")
    assert kwargs["headers"] == {"xi-api-key": "xi_test"}
    assert kwargs["data"]["name"] == "Dr Twin voice"
    assert kwargs["file_names"] == ["sample.mp3"]

    db_session.expire_all()
    config = db_session.query(AvatarConfiguration).filter_by(avatar_id=avatar.id).one()
    assert config.elevenlabs_voice_id == "clone_1"
    assert config.voice_provider == "elevenlabs"
    assert config.voice_clone_name == "Dr Twin voice"
    assert config.voice_clone_consent_at is not None
    event = (
        db_session.query(AuditEvent)
        .filter_by(action="avatar.voice_clone_created")
        .one()
    )
    assert event.actor_user_id == publisher.id


def test_unverified_clone_keeps_current_voice(client, db_session, avatar, elevenlabs):
    elevenlabs.responses[("POST", "/v1/voices/add")] = (
        200,
        {"voice_id": "clone_2", "requires_verification": True},
    )
    res = _clone(client, avatar.id)
    assert res.json()["requires_verification"] is True
    db_session.expire_all()
    config = db_session.query(AvatarConfiguration).filter_by(avatar_id=avatar.id).one()
    assert config.voice_provider is None
    assert config.additional_settings["voiceCloneRequiresVerification"] is True


def test_provider_validation_error_becomes_friendly_400(client, avatar, elevenlabs):
    elevenlabs.responses[("POST", "/v1/voices/add")] = (
        422,
        {"detail": [{"msg": "account abc too short"}]},
    )
    res = _clone(client, avatar.id)
    assert res.status_code == 400
    assert "account abc" not in res.text
    assert "5 seconds" in res.json()["message"]


def test_provider_quota_error_becomes_502(client, avatar, elevenlabs):
    elevenlabs.responses[("POST", "/v1/voices/add")] = (401, {"detail": "quota"})
    res = _clone(client, avatar.id)
    assert res.status_code == 502
    assert "plan/quota" in res.json()["message"]


def test_missing_key_gives_503(client, avatar, elevenlabs, monkeypatch):
    monkeypatch.setattr(voice_service.settings, "elevenlabs_api_key", "")
    res = _clone(client, avatar.id)
    assert res.status_code == 503
    assert res.json()["message"] == "Voice cloning isn't configured on the server"


def test_daily_clone_limit(client, avatar, elevenlabs, monkeypatch):
    monkeypatch.setattr(voice_service.settings, "voice_clone_daily_limit", 1)
    assert _clone(client, avatar.id).status_code == 200
    assert _clone(client, avatar.id).status_code == 429


def test_delete_clears_the_clone(client, db_session, avatar, elevenlabs):
    assert _clone(client, avatar.id).status_code == 200
    res = client.delete(f"/api/publisher/avatars/{avatar.id}/voice-clone")
    assert res.status_code == 200
    assert ("DELETE", "https://api.elevenlabs.io/v1/voices/clone_1") in [
        c[:2] for c in elevenlabs.calls
    ]
    db_session.expire_all()
    config = db_session.query(AvatarConfiguration).filter_by(avatar_id=avatar.id).one()
    assert config.elevenlabs_voice_id is None
    assert config.voice_clone_consent_at is None
    assert config.voice_provider == "openai"


def test_delete_never_removes_a_stock_voice(client, db_session, avatar, elevenlabs):
    config = db_session.query(AvatarConfiguration).filter_by(avatar_id=avatar.id).one()
    config.voice_provider, config.elevenlabs_voice_id = "elevenlabs", "stock_voice"
    db_session.commit()
    res = client.delete(f"/api/publisher/avatars/{avatar.id}/voice-clone")
    assert res.status_code == 404
    assert elevenlabs.calls == []


def test_configuration_saves_avatar_and_voice_choice(client, avatar):
    url = f"/api/publisher/avatars/{avatar.id}/configuration"
    res = client.put(
        url,
        json={
            "heygen_avatar_id": "la_1",
            "voice_provider": "elevenlabs",
            "elevenlabs_voice_id": "v1",
        },
    )
    assert res.status_code == 200, res.text
    body = client.get(url).json()
    assert (
        body["heygen_avatar_id"],
        body["voice_provider"],
        body["elevenlabs_voice_id"],
    ) == ("la_1", "elevenlabs", "v1")
    assert client.put(url, json={"voice_provider": "robot"}).status_code == 422
    assert client.put(url, json={"elevenlabs_voice_id": None}).status_code == 400


def test_configuration_cannot_silently_replace_a_clone(client, avatar, elevenlabs):
    assert _clone(client, avatar.id).status_code == 200
    url = f"/api/publisher/avatars/{avatar.id}/configuration"
    assert client.put(url, json={"elevenlabs_voice_id": "other"}).status_code == 409
    assert client.put(url, json={"voice_provider": "openai"}).status_code == 200


def test_session_token_carries_avatar_and_voice(
    client, db_session, avatar, publisher, test_session, monkeypatch
):
    config = db_session.query(AvatarConfiguration).filter_by(avatar_id=avatar.id).one()
    config.heygen_avatar_id = "la_1"
    config.voice_provider = "elevenlabs"
    config.elevenlabs_voice_id = "v1"
    config.additional_settings = {"renderType": "heygen"}
    test_session.avatar_id = avatar.id
    run = SessionRun(
        id=uuid.uuid4(),
        session_run_id=f"r_{uuid.uuid4().hex[:8]}",
        user_id=publisher.id,
        session_id=test_session.id,
        assistant_parameters={},
        start_time=datetime.utcnow(),
    )
    db_session.add(run)
    db_session.commit()

    async def fake_token(*a, **k):
        return {"client_secret": {"value": "ek"}, "server_instructions": "x"}

    monkeypatch.setattr(
        sessions_api.openai_service, "generate_ephemeral_token", fake_token
    )
    monkeypatch.setattr(sessions_api, "get_run_context", lambda *a, **k: (None, []))

    async def fake_get_session(db, session_id):
        return object()

    monkeypatch.setattr(sessions_api.session_service, "get_session", fake_get_session)
    app.dependency_overrides[get_optional_user] = lambda: publisher
    res = client.get(
        "/api/session/ephemeral",
        params={
            "session_id": test_session.session_id,
            "session_run_id": run.session_run_id,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["heygen_avatar_id"] == "la_1"
    assert body["avatar_render_type"] == "heygen"
    assert (body["voice_provider"], body["voice_id"]) == ("elevenlabs", "v1")


def test_unverified_clone_is_not_sent_to_sessions():
    config = AvatarConfiguration(
        voice_provider="elevenlabs",
        elevenlabs_voice_id="clone_2",
        additional_settings={"voiceCloneRequiresVerification": True},
    )
    media = sessions_api._avatar_media(config)
    assert (media["voice_provider"], media["voice_id"]) == (None, None)


# ── Deleting an avatar removes its API-made clone (best effort) ──────────────


def test_deleting_avatar_deletes_its_clone(client, db_session, avatar, elevenlabs):
    assert _clone(client, avatar.id).status_code == 200
    elevenlabs.calls = []
    res = client.delete(f"/api/publisher/avatars/{avatar.id}")
    assert res.status_code == 204
    assert ("DELETE", "https://api.elevenlabs.io/v1/voices/clone_1") in [
        (c[0], c[1]) for c in elevenlabs.calls
    ]


def test_deleting_avatar_keeps_stock_voice(client, db_session, avatar, elevenlabs):
    avatar.configuration.elevenlabs_voice_id = "stock_voice"
    db_session.commit()
    assert client.delete(f"/api/publisher/avatars/{avatar.id}").status_code == 204
    assert [c for c in elevenlabs.calls if c[0] == "DELETE"] == []


def test_avatar_delete_survives_provider_failure(
    client, db_session, avatar, elevenlabs, caplog
):
    assert _clone(client, avatar.id).status_code == 200
    elevenlabs.responses[("DELETE", "/v1/voices/clone_1")] = (
        500,
        {"detail": "secret provider text"},
    )
    assert client.delete(f"/api/publisher/avatars/{avatar.id}").status_code == 204
    assert db_session.get(Avatar, avatar.id) is None
    assert "secret provider text" not in caplog.text
    assert "Could not delete voice clone" in caplog.text


# ── /api/voices/authorize (used by the frontend TTS route) ───────────────────


def test_authorize_default_voice(client, avatar):
    assert client.post("/api/voices/authorize", json={}).json()["allowed"] is True


def test_authorize_owner_clone(client, avatar, elevenlabs):
    assert _clone(client, avatar.id).status_code == 200
    res = client.post("/api/voices/authorize", json={"voice_id": "clone_1"})
    assert res.status_code == 200 and res.json()["reason"] == "avatar"


def test_authorize_refuses_foreign_unpublished_clone(
    client, db_session, avatar, elevenlabs
):
    assert _clone(client, avatar.id).status_code == 200
    other = User(
        id=uuid.uuid4(),
        username=f"s_{uuid.uuid4().hex[:8]}",
        email=f"s_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        first_name="S",
        last_name="T",
        role="subscriber",
    )
    db_session.add(other)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: other
    res = client.post("/api/voices/authorize", json={"voice_id": "clone_1"})
    assert res.status_code == 403


def test_authorize_stock_voice_and_refuse_unknown(client, avatar, elevenlabs):
    voice_service._category_cache.clear()
    elevenlabs.responses[("GET", "/v1/voices/stock_1")] = (200, {"category": "premade"})
    elevenlabs.responses[("GET", "/v1/voices/other_clone")] = (
        200,
        {"category": "cloned"},
    )
    assert (
        client.post("/api/voices/authorize", json={"voice_id": "stock_1"}).status_code
        == 200
    )
    assert (
        client.post(
            "/api/voices/authorize", json={"voice_id": "other_clone"}
        ).status_code
        == 403
    )


def test_authorize_requires_sign_in(avatar):
    from fastapi.testclient import TestClient

    app.dependency_overrides.pop(get_current_user, None)
    res = TestClient(app).post("/api/voices/authorize", json={})
    assert res.status_code in (401, 403)


def test_free_plan_gets_a_clear_upgrade_message(client, avatar, elevenlabs):
    elevenlabs.responses[("POST", "/v1/voices/add")] = (
        400,
        {"detail": {"status": "can_not_use_instant_voice_cloning", "message": "x"}},
    )
    res = _clone(client, avatar.id)
    assert res.status_code == 402
    assert "paid ElevenLabs plan" in res.text
