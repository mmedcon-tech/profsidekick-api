import json
import logging
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database.connection import get_db, get_redis
from app.database.models import User
from app.database.models.integrations import BrightspaceToken
from app.dependencies.auth import require_publisher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/brightspace", tags=["brightspace"])

_AUTH_URL = "https://auth.brightspace.com/core/connect/authorize"
_TOKEN_URL = "https://auth.brightspace.com/core/connect/token"
_SCOPES = "content:topics:readonly content:modules:readonly content:file:read enrollments:orgunit:readonly"
_STATE_TTL = 300  # seconds — matches Brightspace session timeout expectations


@router.get("/auth")
async def initiate_oauth(
    brightspace_url: str = Query(..., description="Publisher's institution Brightspace base URL, e.g. https://nyu.brightspace.com"),
    current_user: User = Depends(require_publisher),
    redis=Depends(get_redis),
):
    """Redirect the publisher to Brightspace's OAuth2 consent page."""
    if not settings.brightspace_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Brightspace integration is not configured on this server",
        )

    brightspace_url = brightspace_url.rstrip("/")

    state = secrets.token_urlsafe(32)
    await redis.setex(
        f"bs_oauth_state:{state}",
        _STATE_TTL,
        json.dumps({"user_id": str(current_user.id), "brightspace_url": brightspace_url}),
    )

    params = {
        "response_type": "code",
        "client_id": settings.brightspace_client_id,
        "redirect_uri": settings.brightspace_redirect_uri,
        "scope": _SCOPES,
        "state": state,
    }
    return RedirectResponse(url=f"{_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Brightspace redirects the browser here after the publisher grants consent.
    No JWT is present — the publisher's identity is recovered from the Redis state entry.
    """
    frontend = settings.frontend_url.rstrip("/")

    state_raw = await redis.get(f"bs_oauth_state:{state}")
    if not state_raw:
        return RedirectResponse(
            url=f"{frontend}/publisher/settings?brightspace=error&reason=invalid_state"
        )

    await redis.delete(f"bs_oauth_state:{state}")
    state_data = json.loads(state_raw)
    user_id: str = state_data["user_id"]
    brightspace_url: str = state_data["brightspace_url"]

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.brightspace_redirect_uri,
                    "client_id": settings.brightspace_client_id,
                    "client_secret": settings.brightspace_client_secret,
                },
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("Brightspace token exchange HTTP error: %s – %s", exc.response.status_code, exc.response.text)
        return RedirectResponse(
            url=f"{frontend}/publisher/settings?brightspace=error&reason=token_exchange"
        )
    except httpx.RequestError as exc:
        logger.error("Brightspace token exchange network error: %s", exc)
        return RedirectResponse(
            url=f"{frontend}/publisher/settings?brightspace=error&reason=network"
        )

    token_data = resp.json()
    expires_at = None
    if "expires_in" in token_data:
        expires_at = datetime.utcnow() + timedelta(seconds=int(token_data["expires_in"]))

    existing = db.query(BrightspaceToken).filter(BrightspaceToken.user_id == user_id).first()
    if existing:
        existing.brightspace_base_url = brightspace_url
        existing.access_token = token_data["access_token"]
        existing.refresh_token = token_data.get("refresh_token")
        existing.expires_at = expires_at
        existing.updated_at = datetime.utcnow()
    else:
        db.add(BrightspaceToken(
            user_id=user_id,
            brightspace_base_url=brightspace_url,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
        ))

    db.commit()
    return RedirectResponse(url=f"{frontend}/publisher/settings?brightspace=connected")


@router.get("/status")
async def connection_status(
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """Return whether the current publisher has a connected Brightspace account."""
    token_row = db.query(BrightspaceToken).filter(
        BrightspaceToken.user_id == current_user.id
    ).first()

    if not token_row:
        return {"connected": False}

    return {
        "connected": True,
        "brightspace_url": token_row.brightspace_base_url,
        "expires_at": token_row.expires_at.isoformat() if token_row.expires_at else None,
    }


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """Remove the stored Brightspace token for the current publisher."""
    token_row = db.query(BrightspaceToken).filter(
        BrightspaceToken.user_id == current_user.id
    ).first()
    if token_row:
        db.delete(token_row)
        db.commit()
