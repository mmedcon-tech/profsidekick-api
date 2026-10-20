"""
Validation for POST /api/ai/answer, which forwards a chat completion to OpenAI
with the server's API key. Without limits it would let any caller spend the
key on any model, so only a small, explicit request shape is forwarded.
"""

from __future__ import annotations

from typing import Any, Dict, List


class AiProxyRequestError(ValueError):
    pass


_ALLOWED_KEYS = {"model", "messages", "max_tokens", "temperature", "response_format"}


def build_proxy_payload(
    body: Any, *, allowed_models: List[str], max_tokens_cap: int
) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise AiProxyRequestError("Request body must be a JSON object")
    unknown = set(body) - _ALLOWED_KEYS
    if unknown:
        raise AiProxyRequestError(f"Unsupported fields: {', '.join(sorted(unknown))}")

    model = body.get("model")
    if model not in allowed_models:
        raise AiProxyRequestError(f"Model must be one of: {', '.join(allowed_models)}")

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise AiProxyRequestError("messages must be a non-empty list")

    max_tokens = body.get("max_tokens", max_tokens_cap)
    if not isinstance(max_tokens, int) or max_tokens < 1:
        raise AiProxyRequestError("max_tokens must be a positive integer")

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": min(max_tokens, max_tokens_cap),
        "stream": False,
    }
    for key in ("temperature", "response_format"):
        if key in body:
            payload[key] = body[key]
    return payload
