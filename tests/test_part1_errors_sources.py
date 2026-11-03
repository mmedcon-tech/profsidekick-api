import asyncio
from types import SimpleNamespace

import pytest

from app.services.ai import errors
from app.services.ai.adapters import openai_adapter as oa
from app.services.care import guidance


class _Exc(Exception):
    def __init__(self, status=None, code=None, rid="req_abc123"):
        self.status_code, self.code, self.request_id = status, code, rid


@pytest.mark.parametrize("exc,kind", [
    (_Exc(401, "invalid_api_key"), "auth"),
    (_Exc(403), "access"),
    (_Exc(404, "model_not_found"), "access"),
    (_Exc(429, "insufficient_quota"), "quota"),
    (_Exc(429), "rate_limited"),
    (asyncio.TimeoutError(), "timeout"),
    (_Exc(500), "unavailable"),
])
def test_failure_categories_and_request_id(exc, kind):
    e = oa.map_error(exc)
    assert e.kind == kind
    if not isinstance(exc, asyncio.TimeoutError):
        assert e.provider_request_id == "req_abc123"
    assert e.retryable is (kind in ("rate_limited", "timeout", "unavailable"))


def _resp(content, rid="req_ok1"):
    return SimpleNamespace(_request_id=rid, usage=None,
                           choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _gen(monkeypatch, resp):
    class Fake:
        def __init__(self, **kw):
            async def create(**kw):
                return resp
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
    import openai
    monkeypatch.setattr(openai, "AsyncOpenAI", Fake)
    return asyncio.run(oa.OpenAIAdapter("sk-test").generate([{"role": "user", "content": "x"}], model="m", timeout=2))


def test_success_carries_request_id(monkeypatch):
    assert _gen(monkeypatch, _resp("hello")).provider_request_id == "req_ok1"


@pytest.mark.parametrize("resp", [_resp(""), SimpleNamespace(_request_id="req_ok1", choices=[], usage=None)])
def test_unparseable_response_is_parsing_category(monkeypatch, resp):
    with pytest.raises(errors.InvalidOutput) as ei:
        _gen(monkeypatch, resp)
    assert ei.value.kind == "parsing" and ei.value.provider_request_id == "req_ok1"


def test_duplicate_source_titles_collapse_and_renumber():
    srcs = [{"n": 1, "title": "Luteal phase support"}, {"n": 2, "title": "Luteal phase support"},
            {"n": 3, "title": "Embryo transfer"}]
    reply, out = guidance.dedupe_sources("A [1]. B [2]. C [3]. D [1][2].", srcs)
    assert reply == "A [1]. B [1]. C [2]. D [1]."
    assert [(s["n"], s["title"]) for s in out] == [(1, "Luteal phase support"), (2, "Embryo transfer")]


def test_dedupe_drops_uncited_sources():
    reply, out = guidance.dedupe_sources("Only [2].", [{"n": 1, "title": "A"}, {"n": 2, "title": "B"}])
    assert reply == "Only [1]." and [s["title"] for s in out] == ["B"]
