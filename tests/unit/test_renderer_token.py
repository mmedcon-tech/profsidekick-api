"""B4: LiveAvatar sessions are started only by the API, for signed-in users. No database."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.renderer import api as renderer_api
from app.dependencies.auth import get_current_user
from app.main import app

client = TestClient(app)

TOKEN_OK = {"data": {"session_id": "s1", "session_token": "st_1"}}
START_OK = {
    "data": {
        "session_id": "s1",
        "livekit_url": "wss://lk.example",
        "livekit_client_token": "lk_tok",
        "ws_url": "wss://ws.example",
    }
}


class _Res:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    calls = []
    responses = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeClient.calls.append((url, headers, json))
        key = url.rsplit("/", 1)[-1]
        return _Res(_FakeClient.responses.get(key, {}))


@pytest.fixture
def liveavatar(monkeypatch):
    _FakeClient.calls = []
    _FakeClient.responses = {"token": TOKEN_OK, "start": START_OK, "stop": {"code": 1000}}
    monkeypatch.setattr(renderer_api.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(renderer_api.settings, "heygen_enabled", True)
    monkeypatch.setattr(renderer_api.settings, "liveavatar_api_key", "k_test")
    monkeypatch.setattr(renderer_api.settings, "liveavatar_default_avatar_id", "av_default")
    return _FakeClient


@pytest.fixture
def signed_in():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role="subscriber"
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_anonymous_callers_get_no_session(liveavatar):
    res = client.post("/api/renderer/liveavatar-session", json={})
    assert res.status_code in (401, 403)
    assert liveavatar.calls == []


def test_signed_in_user_gets_livekit_credentials(liveavatar, signed_in):
    res = client.post("/api/renderer/liveavatar-session", json={"avatar_id": "av_1"})
    assert res.status_code == 200
    body = res.json()
    assert body["livekit_url"] == "wss://lk.example"
    assert body["livekit_client_token"] == "lk_tok"
    assert body["session_id"] == "s1"
    token_call, start_call = liveavatar.calls
    assert token_call[1]["X-API-KEY"] == "k_test"
    assert token_call[2]["mode"] == "LITE" and token_call[2]["avatar_id"] == "av_1"
    assert start_call[1] == {"Authorization": "Bearer st_1"}


def test_default_avatar_is_used(liveavatar, signed_in):
    client.post("/api/renderer/liveavatar-session", json={})
    assert liveavatar.calls[0][2]["avatar_id"] == "av_default"


def test_disabled_renderer_starts_nothing(liveavatar, signed_in, monkeypatch):
    monkeypatch.setattr(renderer_api.settings, "heygen_enabled", False)
    assert client.post("/api/renderer/liveavatar-session", json={}).status_code == 503
    assert liveavatar.calls == []


def test_provider_error_is_a_502_without_details(liveavatar, signed_in):
    liveavatar.responses["token"] = {"error": "quota"}
    res = client.post("/api/renderer/liveavatar-session", json={})
    assert res.status_code == 502
    assert "quota" not in res.text


def test_stop_session(liveavatar, signed_in):
    res = client.post("/api/renderer/liveavatar-session/stop", json={"session_id": "s1"})
    assert res.status_code == 200 and res.json() == {"stopped": True}
    assert liveavatar.calls[0][2]["session_id"] == "s1"
