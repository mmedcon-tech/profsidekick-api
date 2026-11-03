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


def map_error(exc: BaseException) -> errors.ModelError:
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
    if code in _AUTH or name in ("AuthenticationError", "PermissionDeniedError") or status in (401, 403):
        return errors.Auth(code or "auth")
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
        text = (resp.choices[0].message.content or "").strip()
        u = getattr(resp, "usage", None)
        return Generation(text, self.id, model, parse_structured(text, schema),
                          {"in": getattr(u, "prompt_tokens", 0), "out": getattr(u, "completion_tokens", 0)} if u else {})

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
