"""
Smoke tests for app-level endpoints and the OpenAI proxy.

Endpoints these tests used to call (/api/classes/create, /api/ai/explain,
/api/stats, /api/sessions/{id}/slides) no longer exist and were removed from
this file. OpenAI is never called: the HTTP client is replaced in each test.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.sessions import api as sessions_api
from app.dependencies.auth import get_current_user
from app.main import app

client = TestClient(app)


class TestHealthEndpoints:
    def test_health_check(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "app" in data

    def test_root_endpoint(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data
        assert "docs" in data


class TestEphemeralToken:
    def test_requires_session_and_run_ids(self):
        response = client.get("/api/session/ephemeral")
        assert response.status_code == 422


class _FakeResponse:
    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


class _FakeAsyncClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeAsyncClient.calls.append(json)
        return _FakeResponse()


@pytest.fixture
def fake_openai(monkeypatch):
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(sessions_api.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient.calls


@pytest.fixture
def signed_in():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role="publisher"
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


VALID = {"model": "gpt-4.1-mini", "messages": [{"role": "user", "content": "Hi"}]}


class TestAiProxy:
    def test_refuses_anonymous_callers(self, fake_openai):
        response = client.post("/api/ai/answer", json=VALID)
        assert response.status_code in (401, 403)
        assert fake_openai == []

    def test_forwards_an_allowed_request_with_capped_output(
        self, signed_in, fake_openai
    ):
        response = client.post("/api/ai/answer", json={**VALID, "max_tokens": 10**6})
        assert response.status_code == 200
        assert fake_openai[0]["model"] == "gpt-4.1-mini"
        assert fake_openai[0]["max_tokens"] == sessions_api.settings.ai_proxy_max_tokens
        assert fake_openai[0]["stream"] is False

    @pytest.mark.parametrize(
        "body",
        [
            {**VALID, "model": "o1-pro"},
            {**VALID, "messages": []},
            {**VALID, "stream": True},
            {**VALID, "tools": []},
            {"messages": VALID["messages"]},
        ],
    )
    def test_rejects_disallowed_requests(self, signed_in, fake_openai, body):
        response = client.post("/api/ai/answer", json=body)
        assert response.status_code == 422
        assert fake_openai == []
