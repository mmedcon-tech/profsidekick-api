"""Non-retryable OpenAI errors (credit/quota/auth) skip the retry and fall back to the KB fast."""
import asyncio
import time

import pytest

from app.services.care import health
from tests.test_care_platform import stub_ai, world  # noqa: F401


class _Quota(Exception):
    status_code = 429
    code = "credit_balance_exhausted"


class _Transient(Exception):
    status_code = 503


@pytest.fixture(autouse=True)
def _reset():
    health.reset_breaker()
    yield
    health.reset_breaker()


def test_non_retryable_classification():
    assert health.non_retryable(_Quota())
    q = _Quota(); q.code = None; q.body = {"error": {"code": "insufficient_quota"}}
    assert health.non_retryable(q)
    assert not health.non_retryable(_Transient())


def test_breaker_opens_only_on_non_retryable():
    assert health.note_failure(_Transient()) is False and health.openai_available()
    assert health.note_failure(_Quota()) is True and not health.openai_available()
    assert health.blocked_kind() == "quota"


def test_care_chat_quota_error_one_attempt_then_kb_under_budget(world, stub_ai, monkeypatch):
    from app.database.models import CareProgram
    from app.services.care import chat
    from tests.test_care_integrity import WM, _approve_item
    from tests.test_care_platform import _as, _enroll, _user

    c, db, staff = world["client"], world["db"], world["staff"]
    _as(staff)
    pid = str(db.query(CareProgram).filter_by(slug="a-weight-management").first().id)
    _approve_item(c, pid, "Egg collection leaflet", "Egg collection is a short procedure under sedation.")
    pat = _user(db)
    _as(pat)
    _enroll(c, "demo-clinic-a", "a-weight-management")
    calls = []

    async def quota(msgs):
        calls.append(1)
        raise _Quota()

    monkeypatch.setattr(chat, "_complete", quota)
    t = time.monotonic()
    r = c.post(f"{WM}/messages", json={"content": "egg collection sedation"}).json()["result"]
    assert time.monotonic() - t < 5
    assert len(calls) == 1  # no retry on a billing error
    assert r["type"] == "education" and r["provenance"] == "source_quote"
    assert r["text"].startswith("From your clinic's knowledge base:") and "model" not in r["text"].lower()
    # the next request does not call the provider at all while the breaker is open
    c.post(f"{WM}/messages", json={"content": "egg collection sedation"})
    assert len(calls) == 1


def test_fertility_complete_skips_provider_when_breaker_open(monkeypatch):
    from app.services.fertility import consultation

    health.note_failure(_Quota())
    monkeypatch.setattr(consultation, "_llm_client", lambda: (_ for _ in ()).throw(AssertionError("called")))
    t = time.monotonic()
    with pytest.raises(RuntimeError):
        asyncio.run(consultation._complete([{"role": "user", "content": "x"}]))
    assert time.monotonic() - t < 0.1


def test_embeddings_skipped_when_breaker_open(monkeypatch):
    from app.services.fertility import knowledge

    monkeypatch.setattr(knowledge.__dict__.get("settings", None) or __import__("app.config", fromlist=["settings"]).settings,
                        "openai_api_key", "sk-" + "a" * 40, raising=False)
    health.note_failure(_Quota())
    assert knowledge._try_embed(["egg retrieval"]) is None
