"""
Renderer provider sessions (V2_IMPLEMENTATION_PLAN B4).

Streaming avatars run on HeyGen LiveAvatar (the HeyGen streaming API was
retired). The API holds LIVEAVATAR_API_KEY, and only signed-in users can open a
session. Sessions use LITE mode: LiveAvatar streams the avatar video over
LiveKit, and the client sends the voice audio (ElevenLabs) over ws_url.
Phase 5 moves this to POST /variants/{id}/renderer-session with per-run
scoping and minute metering (v2 §6.3).
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.database.models import User
from app.dependencies.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/renderer", tags=["renderer"])

LIVEAVATAR_BASE_URL = "https://api.liveavatar.com/v1"


class LiveAvatarSessionRequest(BaseModel):
    avatar_id: Optional[str] = None
    quality: Optional[str] = None  # very_high | high | medium | low


class LiveAvatarStopRequest(BaseModel):
    session_id: str


def _require_enabled() -> None:
    if not settings.heygen_enabled or not settings.liveavatar_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Streaming avatar is not enabled",
        )


def _api_key_headers() -> dict:
    return {"X-API-KEY": settings.liveavatar_api_key, "Content-Type": "application/json"}


@router.post("/liveavatar-session")
async def create_liveavatar_session(
    body: LiveAvatarSessionRequest,
    current_user: User = Depends(get_current_user),
):
    """Mint a LITE session token and start it. Returns LiveKit credentials."""
    _require_enabled()
    avatar_id = body.avatar_id or settings.liveavatar_default_avatar_id
    if not avatar_id:
        raise HTTPException(status_code=400, detail="No avatar_id given or configured")

    payload = {
        "mode": "LITE",
        "avatar_id": avatar_id,
        "is_sandbox": settings.liveavatar_sandbox,
        "video_settings": {"quality": body.quality or "medium", "encoding": "H264"},
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            tok = await client.post(
                f"{LIVEAVATAR_BASE_URL}/sessions/token", headers=_api_key_headers(), json=payload
            )
            tok.raise_for_status()
            tok_data = tok.json().get("data") or {}
            session_token = tok_data.get("session_token")
            if not session_token:
                raise ValueError("no session_token in response")
            start = await client.post(
                f"{LIVEAVATAR_BASE_URL}/sessions/start",
                headers={"Authorization": f"Bearer {session_token}"},
            )
            start.raise_for_status()
            data = start.json().get("data") or {}
    except Exception as exc:
        logger.error("LiveAvatar session start failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start a streaming avatar session",
        )
    if not data.get("livekit_url") or not data.get("livekit_client_token"):
        raise HTTPException(status_code=502, detail="LiveAvatar returned no LiveKit credentials")

    logger.info("LiveAvatar session %s started for user %s", data.get("session_id"), current_user.id)
    return {
        "session_id": data.get("session_id") or tok_data.get("session_id"),
        "livekit_url": data["livekit_url"],
        "livekit_client_token": data["livekit_client_token"],
        "ws_url": data.get("ws_url"),
        "max_session_duration": data.get("max_session_duration"),
    }


@router.post("/liveavatar-session/stop")
async def stop_liveavatar_session(
    body: LiveAvatarStopRequest,
    current_user: User = Depends(get_current_user),
):
    _require_enabled()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                f"{LIVEAVATAR_BASE_URL}/sessions/stop",
                headers=_api_key_headers(),
                json={"session_id": body.session_id, "reason": "USER_CLOSED"},
            )
            res.raise_for_status()
    except Exception as exc:
        logger.warning("LiveAvatar stop failed for %s: %s", body.session_id, exc)
        return {"stopped": False}
    return {"stopped": True}
