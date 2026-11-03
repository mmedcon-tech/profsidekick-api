"""OpenAI adapter. The only care/clinical-path module that imports the OpenAI SDK."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Dict, List, Optional, Type

from pydantic import BaseModel

from app.services.ai import errors
from app.services.ai.base import Generation, parse_structured

_NON_RETRYABLE = {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached",
                  "billing_not_active", "account_deactivated"}
_AUTH = {"invalid_api_key", "invalid_organization"}
_ACCESS = {"model_not_found", "unsupported_country_region_territory", "project_not_found"}


def _request_id(exc_or_resp) -> str | None:
    rid = getattr(exc_or_resp, "request_id", None) or getattr(exc_or_resp, "_request_id", None)
    if not rid:
        headers = getattr(getattr(exc_or_resp, "response", None), "headers", None)
        rid = headers.get("x-request-id") if headers is not None else None
    return rid if isinstance(rid, str) and len(rid) < 128 else None


def map_error(exc: BaseException) -> errors.ModelError:
    err = _map(exc)
    err.provider_request_id = err.provider_request_id or _request_id(exc)
    return err


def _map(exc: BaseException) -> errors.ModelError:
    if isinstance(exc, errors.ModelError):
        return exc
    if isinstance(exc, asyncio.TimeoutError):
        return errors.Timeout("timeout")
    name = type(exc).__name__
    code = getattr(exc, "code", None)
    body = getattr(exc, "body", None)
    if not code and isinstance(body, dict):
        code = (body.get("error") or body).get("code") if isinstance(body.get("error") or body, dict) else None
    status = getattr(exc, "status_code", None)
    if code in _NON_RETRYABLE or status == 402:
        return errors.Quota(code or "quota")
    if code in _AUTH or name == "AuthenticationError" or status == 401:
        return errors.Auth(code or "auth")
    if code in _ACCESS or name in ("PermissionDeniedError", "NotFoundError") or status in (403, 404):
        return errors.Access(code or "access")
    if name == "RateLimitError" or status == 429:
        return errors.RateLimited("rate_limited")
    if name in ("APITimeoutError",):
        return errors.Timeout("timeout")
    if name in ("APIConnectionError", "InternalServerError") or (status or 0) >= 500:
        return errors.Unavailable(name)
    return errors.ModelError(name)


class OpenAIAdapter:
    id = "openai"

    def __init__(self, api_key: Optional[str]):
        self._key = api_key

    def _check(self):
        if not self._key or not self._key.startswith("sk-"):
            raise errors.Config("missing key")

    async def generate(self, messages: List[Dict[str, str]], *, model: str, timeout: float,
                       temperature: float = 0.3, schema: Optional[Type[BaseModel]] = None) -> Generation:
        self._check()
        from openai import AsyncOpenAI

        kw = {"response_format": {"type": "json_object"}} if schema else {}
        try:
            resp = await asyncio.wait_for(
                AsyncOpenAI(api_key=self._key, timeout=timeout, max_retries=0).chat.completions.create(
                    model=model, messages=messages, temperature=temperature, **kw), timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            raise map_error(exc) from None
        rid = _request_id(resp)
        try:
            text = (resp.choices[0].message.content or "").strip()
            if not text:
                raise errors.InvalidOutput("empty")
            parsed = parse_structured(text, schema)
        except errors.ModelError as e:
            e.provider_request_id = rid
            raise
        except Exception:  # noqa: BLE001 - malformed response object
            e = errors.InvalidOutput("malformed")
            e.provider_request_id = rid
            raise e from None
        u = getattr(resp, "usage", None)
        return Generation(text, self.id, model, parsed,
                          {"in": getattr(u, "prompt_tokens", 0), "out": getattr(u, "completion_tokens", 0)} if u else {},
                          rid)

    async def stream(self, messages, *, model: str, timeout: float, temperature: float = 0.3) -> AsyncIterator[str]:
        self._check()
        from openai import AsyncOpenAI

        try:
            s = await AsyncOpenAI(api_key=self._key, timeout=timeout, max_retries=0).chat.completions.create(
                model=model, messages=messages, temperature=temperature, stream=True)
            async for ev in s:
                d = ev.choices[0].delta.content if ev.choices else None
                if d:
                    yield d
        except Exception as exc:  # noqa: BLE001
            raise map_error(exc) from None

    def embed(self, texts: List[str], *, model: str, timeout: float) -> List[List[float]]:
        self._check()
        from openai import OpenAI

        client = OpenAI(api_key=self._key, timeout=timeout, max_retries=0)
        out: List[List[float]] = []
        try:
            for i in range(0, len(texts), 256):
                out.extend(d.embedding for d in client.embeddings.create(model=model, input=texts[i:i + 256]).data)
        except Exception as exc:  # noqa: BLE001
            raise map_error(exc) from None
        return out
