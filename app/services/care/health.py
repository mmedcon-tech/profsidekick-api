"""Sanitized dependency health checks with typed error kinds.

Kinds: config | auth | rate_limit | timeout | upstream | network | playback | unknown.
Results never include keys, key fragments, raw provider messages or user text.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, Optional

from app.config import settings

KINDS = ("config", "auth", "rate_limit", "timeout", "upstream", "network", "playback", "unknown")
PLACEHOLDER_PREFIXES = ("your", "sk-your", "sk-xxx", "sk-placeholder", "sk-test-", "changeme", "replace", "dummy", "example", "xxx")


def key_state(value: Optional[str], prefix: Optional[str] = None) -> str:
    """'missing' | 'placeholder' | 'present' — inspects shape only, never returns the value."""
    v = (value or "").strip().strip("'\"")
    if not v:
        return "missing"
    low = v.lower()
    if low.startswith(PLACEHOLDER_PREFIXES) or "placeholder" in low or len(v) < 20 or (prefix and not v.startswith(prefix)):
        return "placeholder"
    return "present"


def classify(exc: BaseException) -> str:
    from app.services.ai import errors as ai_errors

    if isinstance(exc, ai_errors.ModelError):
        return {"rate_limited": "rate_limit", "unavailable": "upstream", "quota": "quota"}.get(exc.kind, exc.kind)
    name = type(exc).__name__
    code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if code in (401, 403) or "Authentication" in name or "PermissionDenied" in name:
        return "auth"
    if code == 429 or "RateLimit" in name:
        return "rate_limit"
    if "Timeout" in name:
        return "timeout"
    if "Connection" in name or "Connect" in name:
        return "network"
    if isinstance(code, int) and code >= 500:
        return "upstream"
    return "unknown"


def _result(service: str, ok: bool, kind: Optional[str], started: float, rid: str, **extra) -> Dict[str, Any]:
    return {"service": service, "ok": ok, "error_kind": kind, "request_id": rid,
            "latency_ms": int((time.monotonic() - started) * 1000), **extra}


async def check_llm(live: bool = True, request_id: Optional[str] = None) -> Dict[str, Any]:
    rid = request_id or uuid.uuid4().hex[:16]
    t = time.monotonic()
    state = key_state(settings.openai_api_key, "sk-")
    if state != "present":
        return _result("openai", False, "config", t, rid, key=state)
    if not live:
        return _result("openai", True, None, t, rid, key=state, live=False)
    try:
        from openai import AsyncOpenAI

        await AsyncOpenAI(api_key=settings.openai_api_key, timeout=15).models.list()
        return _result("openai", True, None, t, rid, key=state, live=True)
    except Exception as exc:  # noqa: BLE001
        return _result("openai", False, classify(exc), t, rid, key=state, live=True)


async def check_tts(live: bool = True, request_id: Optional[str] = None) -> Dict[str, Any]:
    rid = request_id or uuid.uuid4().hex[:16]
    t = time.monotonic()
    key = os.getenv("ELEVENLABS_API_KEY") or getattr(settings, "elevenlabs_api_key", "")
    state = key_state(key)
    if state != "present":
        return _result("elevenlabs", False, "config", t, rid, key=state)
    if not live:
        return _result("elevenlabs", True, None, t, rid, key=state, live=False)
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.elevenlabs.io/v1/models", headers={"xi-api-key": key})
        if r.status_code == 200:
            # Quota: a valid key with an exhausted character allowance fails every real synthesis.
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    s = await c.get("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": key})
                if s.status_code == 200:
                    d = s.json()
                    used, limit = int(d.get("character_count") or 0), int(d.get("character_limit") or 0)
                    left = max(limit - used, 0)
                    if limit and left < 1000:
                        return _result("elevenlabs", False, "quota", t, rid, key=state, live=True, characters_left=left)
                    return _result("elevenlabs", True, None, t, rid, key=state, live=True, characters_left=left)
            except Exception:  # noqa: BLE001 - quota is best-effort; the key check already passed
                pass
            return _result("elevenlabs", True, None, t, rid, key=state, live=True)
        kind = "auth" if r.status_code in (401, 403) else "rate_limit" if r.status_code == 429 else \
            "upstream" if r.status_code >= 500 else "unknown"
        return _result("elevenlabs", False, kind, t, rid, key=state, live=True, status=r.status_code)
    except Exception as exc:  # noqa: BLE001
        return _result("elevenlabs", False, classify(exc), t, rid, key=state, live=True)


def check_liveavatar(request_id: Optional[str] = None) -> Dict[str, Any]:
    """Config only — a live check would spend LiveAvatar credits."""
    rid = request_id or uuid.uuid4().hex[:16]
    t = time.monotonic()
    state = key_state(os.getenv("LIVEAVATAR_API_KEY") or os.getenv("HEYGEN_API_KEY"))
    has_avatar = bool(os.getenv("LIVEAVATAR_DEFAULT_AVATAR_ID"))
    ok = state == "present" and has_avatar
    return _result("liveavatar", ok, None if ok else "config", t, rid, key=state, avatar_configured=has_avatar,
                   live=False, note="Not called live; sessions consume credits.")


def demo_environment() -> Dict[str, Any]:
    flag = (os.getenv("MYOS_ENVIRONMENT") or "demo").lower()
    return {"environment": flag, "is_demo": flag != "production",
            "notice": "Synthetic demo environment. Not for real patient data." if flag != "production" else None}


# ───────────── non-retryable provider errors: circuit breaker ─────────────
# Billing / quota / auth failures will not succeed on retry. After one, OpenAI calls (chat and embeddings)
# are skipped for OPENAI_BLOCK_S so patients get the knowledge-base answer immediately.
NON_RETRYABLE_CODES = {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached",
                       "billing_not_active", "account_deactivated", "invalid_api_key", "invalid_organization"}
OPENAI_BLOCK_S = float(os.getenv("OPENAI_BLOCK_S") or 120)
_blocked_until = 0.0
_blocked_kind: Optional[str] = None


def error_code(exc: BaseException) -> Optional[str]:
    code = getattr(exc, "code", None)
    body = getattr(exc, "body", None)
    if not code and isinstance(body, dict):
        err = body.get("error")
        code = body.get("code") or (err.get("code") if isinstance(err, dict) else None)
    return code if isinstance(code, str) else None


def non_retryable(exc: BaseException) -> bool:
    from app.services.ai import errors as ai_errors

    if isinstance(exc, ai_errors.ModelError):
        return not exc.retryable
    status_code = getattr(exc, "status_code", None)
    return classify(exc) == "auth" or status_code == 402 or error_code(exc) in NON_RETRYABLE_CODES


def note_failure(exc: BaseException) -> bool:
    """Record a provider failure. Returns True (and opens the breaker) when retrying is pointless."""
    global _blocked_until, _blocked_kind
    if non_retryable(exc):
        _blocked_until = time.monotonic() + OPENAI_BLOCK_S
        k = classify(exc)
        _blocked_kind = k if k in ("auth", "config", "not_eligible") else "quota"
        return True
    return False


def openai_available() -> bool:
    return time.monotonic() >= _blocked_until


def blocked_kind() -> Optional[str]:
    return None if openai_available() else _blocked_kind


def reset_breaker() -> None:
    global _blocked_until, _blocked_kind
    _blocked_until, _blocked_kind = 0.0, None


# --- Voice availability: "Play reply" is shown only when TTS is configured, eligible for the
# clinic's data class, and not known to be out of quota / unauthorised. The live check is free
# (models + subscription endpoints, no synthesis) and cached so it is not run per message.
_TTS_CACHE: Dict[str, Any] = {"at": 0.0, "result": None}
TTS_CACHE_S = 600


def note_tts_result(result: Dict[str, Any]) -> None:
    _TTS_CACHE.update(at=time.monotonic(), result=result)


async def voice_available(clinic, live: bool = True) -> Dict[str, Any]:
    from app.services.ai import registry

    cfg = registry.load()
    why = registry.eligible(cfg, "elevenlabs", "voice", registry.clinic_data_class(cfg, clinic))
    if why:
        return {"available": False, "reason": why}
    cached = _TTS_CACHE["result"]
    if cached is None or time.monotonic() - _TTS_CACHE["at"] > TTS_CACHE_S:
        cached = await check_tts(live=live)
        if live:
            note_tts_result(cached)
    if not cached["ok"]:
        return {"available": False, "reason": cached.get("error_kind") or "unavailable"}
    return {"available": True, "reason": None}
