"""Single entry point for model calls from clinical code.

route = ordered provider:model list for (clinic, task). Each entry is used only if it is
independently eligible for the clinic's data class and the task's capability. Ineligible
entries are skipped *before* any data is sent. Failures move to the next eligible entry;
non-retryable errors (quota/auth/config) open a short per-provider breaker."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services.ai import errors, oplog, registry
from app.services.ai.base import Generation

_factories: Dict[str, Callable[[], Any]] = {}
_instances: Dict[str, Any] = {}
_blocked: Dict[str, Tuple[float, str]] = {}
BLOCK_S = float(os.getenv("OPENAI_BLOCK_S") or 120)

TASK_CAPABILITY = {"generation": "generation", "embeddings": "embeddings", "reranking": "reranking",
                   "transcription": "transcription", "voice": "voice"}


def _default_factory(name: str):
    if name == "openai":
        from app.config import settings
        from app.services.ai.adapters.openai_adapter import OpenAIAdapter
        return OpenAIAdapter(settings.openai_api_key)
    if name == "local":
        from app.services.ai.adapters.local_adapter import LocalAdapter
        return LocalAdapter()
    raise errors.Config(f"no adapter {name}")


def adapter(provider: str, cfg: Optional[Dict[str, Any]] = None):
    cfg = cfg or registry.load()
    name = (cfg["providers"].get(provider) or {}).get("adapter") or provider
    if name not in _instances:
        _instances[name] = _factories[name]() if name in _factories else _default_factory(name)
    return _instances[name]


def install(name: str, instance: Any) -> None:
    """Tests / demos: register a concrete adapter instance."""
    _instances[name] = instance


def reset() -> None:
    _instances.clear()
    _blocked.clear()


def blocked(provider: str) -> Optional[str]:
    b = _blocked.get(provider)
    if b and b[0] > time.monotonic():
        return b[1]
    _blocked.pop(provider, None)
    return None


def note(provider: str, err: errors.ModelError) -> None:
    if not err.retryable:
        _blocked[provider] = (time.monotonic() + BLOCK_S, err.kind)


def plan(clinic, task: str, data_class: Optional[str] = None, cfg=None) -> Tuple[str, List[Tuple[registry.Choice, Optional[str]]]]:
    cfg = cfg or registry.load()
    dc = data_class or registry.clinic_data_class(cfg, clinic)
    cap = TASK_CAPABILITY[task]
    return dc, [(c, registry.eligible(cfg, c.provider, cap, dc, c.model)) for c in
                registry.chain(cfg, getattr(clinic, "slug", None), task)]


async def generate(messages: List[Dict[str, str]], *, clinic, task: str = "generation", data_class: Optional[str] = None,
                   timeout: float = 5.0, temperature: float = 0.3, schema=None,
                   request_id: Optional[str] = None) -> Tuple[Optional[Generation], Dict[str, Any]]:
    """Returns (generation or None, trail). trail has no clinical text."""
    cfg = registry.load()
    dc, steps = plan(clinic, task, data_class, cfg)
    deadline = time.monotonic() + timeout
    trail: Dict[str, Any] = {"data_class": dc, "attempts": [], "llm": "error", "error_kind": "not_eligible"}
    prev = None
    for choice, why_not in steps:
        base = dict(request_id=request_id, clinic=getattr(clinic, "slug", None), task=task, data_class=dc,
                    provider=choice.provider, model=choice.model, fallback_from=prev)
        if why_not:
            trail["attempts"].append(oplog.record(**base, outcome="skipped", skipped=why_not))
            continue
        b = blocked(choice.provider)
        if b:
            trail["attempts"].append(oplog.record(**base, outcome="skipped", skipped="breaker_open", error_kind=b))
            trail["error_kind"] = b
            prev = choice.provider
            continue
        left = deadline - time.monotonic()
        if left < 0.5:
            trail["attempts"].append(oplog.record(**base, outcome="skipped", skipped="deadline"))
            break
        t0 = time.monotonic()
        try:
            g = await asyncio.wait_for(adapter(choice.provider, cfg).generate(
                messages, model=choice.model, timeout=left, temperature=temperature, schema=schema), timeout=left)
        except Exception as exc:  # noqa: BLE001
            err = exc if isinstance(exc, errors.ModelError) else (
                errors.Timeout("timeout") if isinstance(exc, asyncio.TimeoutError) else errors.ModelError(type(exc).__name__))
            note(choice.provider, err)
            trail["attempts"].append(oplog.record(**base, outcome="error", error_kind=err.kind,
                                                  provider_request_id=err.provider_request_id,
                                                  latency_ms=int((time.monotonic() - t0) * 1000)))
            trail["error_kind"] = err.kind
            trail["provider_request_id"] = err.provider_request_id
            prev = choice.provider
            continue
        trail["attempts"].append(oplog.record(**base, outcome="ok", latency_ms=int((time.monotonic() - t0) * 1000),
                                              tokens_in=g.usage.get("in"), tokens_out=g.usage.get("out"),
                                              provider_request_id=g.provider_request_id))
        trail.update(llm="ok", provider=g.provider, model=g.model, error_kind=None,
                     provider_request_id=g.provider_request_id,
                     fallback_reason=trail["attempts"][0].get("error_kind") or trail["attempts"][0].get("skipped")
                     if len(trail["attempts"]) > 1 else None)
        return g, trail
    oplog.record(request_id=request_id, clinic=getattr(clinic, "slug", None), task=task, data_class=dc,
                 outcome="no_provider", error_kind=trail["error_kind"])
    return None, trail


def embed(texts: List[str], *, clinic=None, data_class: str = "public_content", timeout: float = 3.0,
          request_id: Optional[str] = None) -> Tuple[Optional[List[List[float]]], Optional[str]]:
    """Embeddings from the first eligible provider. Returns (vectors, model id) or (None, None).
    Only the *first* eligible provider is used: vectors from different models are not comparable."""
    cfg = registry.load()
    dc, steps = plan(clinic, "embeddings", data_class, cfg)
    for choice, why_not in steps:
        base = dict(request_id=request_id, clinic=getattr(clinic, "slug", None), task="embeddings", data_class=dc,
                    provider=choice.provider, model=choice.model)
        if why_not or blocked(choice.provider):
            oplog.record(**base, outcome="skipped", skipped=why_not or "breaker_open")
            return None, None
        try:
            v = adapter(choice.provider, cfg).embed(texts, model=choice.model, timeout=timeout)
        except errors.ModelError as err:
            note(choice.provider, err)
            oplog.record(**base, outcome="error", error_kind=err.kind)
            return None, None
        oplog.record(**base, outcome="ok")
        return v, f"{choice.provider}:{choice.model}"
    return None, None


def active_embedding_model(clinic=None) -> Optional[str]:
    steps = registry.chain(registry.load(), getattr(clinic, "slug", None), "embeddings")
    return f"{steps[0].provider}:{steps[0].model}" if steps else None
