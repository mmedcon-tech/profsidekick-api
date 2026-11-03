"""What clinical workflow code uses: text completion for the clinic in the current request
context, with eligibility, fallback and the operational log handled by the router."""
from __future__ import annotations

import contextvars
from typing import Any, Dict, List, Optional

from app.services.ai import errors, registry, router

_ctx: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar("myos_ai_ctx", default={})


def bind(clinic=None, request_id: Optional[str] = None, data_class: Optional[str] = None) -> Dict[str, Any]:
    d = {"clinic": clinic, "request_id": request_id, "data_class": data_class, "trail": None}
    _ctx.set(d)
    return d


def last_trail() -> Optional[Dict[str, Any]]:
    return _ctx.get().get("trail")


def ready(task: str = "generation", data_class: Optional[str] = None) -> Optional[str]:
    """None if at least one eligible, configured provider exists for this clinic/task; else
    'not_eligible' or 'config'. No network."""
    from app.config import settings
    from app.services.care.health import key_state

    d = _ctx.get()
    cfg = registry.load()
    _, steps = router.plan(d.get("clinic"), task, data_class or d.get("data_class"), cfg)
    eligible = [c for c, why in steps if not why]
    if not eligible:
        return "not_eligible"
    for c in eligible:
        env = (cfg["providers"][c.provider] or {}).get("key_env")
        if not env:
            return None
        val = getattr(settings, env.lower(), None)
        if key_state(val, "sk-" if c.provider == "openai" else None) == "present":
            return None
    return "config"


async def complete(messages: List[Dict[str, str]], *, temperature: float = 0.3, timeout: float = 5.0) -> str:
    d = _ctx.get()
    g, trail = await router.generate(messages, clinic=d.get("clinic"), data_class=d.get("data_class"),
                                     timeout=timeout, temperature=temperature, request_id=d.get("request_id"))
    if d:
        d["trail"] = trail
    if g is None:
        kind = trail.get("error_kind") or "unknown"
        cls = {"quota": errors.Quota, "auth": errors.Auth, "config": errors.Config, "timeout": errors.Timeout,
               "rate_limited": errors.RateLimited, "unavailable": errors.Unavailable,
               "not_eligible": errors.NotEligible, "invalid_output": errors.InvalidOutput}.get(kind, errors.ModelError)
        raise cls(kind)
    return g.text.strip()


def embed(texts: List[str], *, data_class: str = "public_content", timeout: float = 3.0):
    d = _ctx.get()
    return router.embed(texts, clinic=d.get("clinic"), data_class=data_class, timeout=timeout,
                        request_id=d.get("request_id"))
