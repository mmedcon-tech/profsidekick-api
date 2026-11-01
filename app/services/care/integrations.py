"""Admin-only integration status. Reports configuration and, with live=True,
a cheap read-only provider probe. Never returns key material — only whether
a key is present and whether it looks like a placeholder."""
from __future__ import annotations

import os
import time
from typing import Any, Dict

import httpx

from app.config import settings

PLACEHOLDER_HINTS = ("your_", "here", "xxx", "changeme", "placeholder", "sk-...")


def _key_state(value: str) -> Dict[str, Any]:
    v = (value or "").strip()
    if not v:
        return {"configured": False, "state": "missing"}
    if any(h in v.lower() for h in PLACEHOLDER_HINTS):
        return {"configured": False, "state": "placeholder"}
    return {"configured": True, "state": "present"}


def _probe(method: str, url: str, headers: Dict[str, str]) -> Dict[str, Any]:
    t0 = time.monotonic()
    try:
        r = httpx.request(method, url, headers=headers, timeout=10)
        ok = r.status_code == 200
        detail = None
        if not ok:
            try:
                err = r.json().get("error") or r.json().get("detail")
                detail = err.get("code") if isinstance(err, dict) else (str(err)[:120] if err else None)
            except Exception:  # noqa: BLE001
                detail = None
        return {"ok": ok, "http_status": r.status_code, "detail": detail,
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "http_status": None, "detail": type(exc).__name__}


def status_report(db, live: bool = False) -> Dict[str, Any]:
    openai_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
    eleven_key = os.getenv("ELEVENLABS_API_KEY", "")
    live_key = os.getenv("LIVEAVATAR_API_KEY", "")
    out: Dict[str, Any] = {
        "openai": {**_key_state(openai_key), "used_for": "chat answers, embeddings",
                   "path": "browser → /api/care/p/{clinic}/{program}/messages → backend → api.openai.com"},
        "elevenlabs": {**_key_state(eleven_key), "used_for": "spoken replies (text-to-speech)",
                       "path": "browser → Next /api/tts/elevenlabs (signed-in) → api.elevenlabs.io",
                       "note": "The Next.js server holds its own ELEVENLABS_API_KEY (.env.local); this reports the backend copy."},
        "liveavatar": {**_key_state(live_key), "used_for": "talking avatar video (LITE mode, audio pushed over ws)",
                       "default_avatar_configured": bool(os.getenv("LIVEAVATAR_DEFAULT_AVATAR_ID")),
                       "note": "Not probed live: starting a session uses credits."},
    }
    if live:
        if out["openai"]["configured"]:
            out["openai"]["probe"] = _probe("GET", "https://api.openai.com/v1/models", {"Authorization": f"Bearer {openai_key}"})
        else:
            out["openai"]["probe"] = {"ok": False, "detail": f"not probed: key {out['openai']['state']}"}
        if out["elevenlabs"]["configured"]:
            out["elevenlabs"]["probe"] = _probe("GET", "https://api.elevenlabs.io/v1/voices", {"xi-api-key": eleven_key})
    try:
        from sqlalchemy import text

        out["database"] = {"ok": True, "pgvector": bool(db.execute(text(
            "select 1 from pg_extension where extname='vector'")).scalar())}
    except Exception as exc:  # noqa: BLE001
        out["database"] = {"ok": False, "detail": type(exc).__name__}
    out["checked_live"] = live
    return out
