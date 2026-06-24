import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import RedirectResponse, StreamingResponse
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
_STATE_TTL = 300  # seconds

_LE_VER = "1.82"   # Learning Environment API
_LP_VER = "1.49"   # Learning Platform (enrollments) API

# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _get_valid_token(user_id: Any, db: Session) -> BrightspaceToken:
    """Return the publisher's Brightspace token, refreshing it first if it is near expiry."""
    token_row = db.query(BrightspaceToken).filter(
        BrightspaceToken.user_id == user_id
    ).first()
    if not token_row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brightspace account not connected. Visit publisher settings to link your account.",
        )

    near_expiry = (
        token_row.expires_at is not None
        and datetime.utcnow() >= token_row.expires_at - timedelta(seconds=60)
    )
    if near_expiry:
        if not token_row.refresh_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Brightspace token expired. Please reconnect your account.",
            )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    _TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": token_row.refresh_token,
                        "client_id": settings.brightspace_client_id,
                        "client_secret": settings.brightspace_client_secret,
                    },
                )
                resp.raise_for_status()
            data = resp.json()
            token_row.access_token = data["access_token"]
            token_row.refresh_token = data.get("refresh_token", token_row.refresh_token)
            if "expires_in" in data:
                token_row.expires_at = datetime.utcnow() + timedelta(seconds=int(data["expires_in"]))
            token_row.updated_at = datetime.utcnow()
            db.commit()
        except httpx.HTTPError as exc:
            logger.error("Brightspace token refresh failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Brightspace token refresh failed. Please reconnect your account.",
            )

    return token_row


async def _bs_get(url: str, token: str) -> Any:
    """GET a Brightspace REST endpoint; raises HTTPException on failure."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})

    if resp.status_code == 403:
        raise HTTPException(status_code=403, detail="Brightspace returned 403 — check your scopes or permissions.")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Brightspace resource not found.")
    if not resp.is_success:
        raise HTTPException(status_code=502, detail=f"Brightspace API error {resp.status_code}.")

    return resp.json()


# ──────────────────────────────────────────────────────────────────────────────
# Phase 1 — OAuth & connection management
# ──────────────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — Browse & import
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/courses")
async def list_courses(
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
) -> List[Dict]:
    """
    List all org units the publisher is enrolled in.
    Returns a flat list; the frontend groups/filters by type.
    """
    token_row = await _get_valid_token(current_user.id, db)
    base = token_row.brightspace_base_url

    data = await _bs_get(
        f"{base}/d2l/api/lp/{_LP_VER}/enrollments/myenrollments/",
        token_row.access_token,
    )

    items = data.get("Items", []) if isinstance(data, dict) else data
    return [
        {
            "orgUnitId": item["OrgUnit"]["Id"],
            "name": item["OrgUnit"]["Name"],
            "code": item["OrgUnit"].get("Code"),
            "type": item["OrgUnit"]["Type"]["Name"],
            "homeUrl": item["OrgUnit"].get("HomeUrl"),
        }
        for item in items
        if item.get("Access", {}).get("CanAccess", True)
    ]


@router.get("/courses/{org_unit_id}/content")
async def list_course_content(
    org_unit_id: int = Path(..., description="Brightspace org unit ID"),
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
) -> List[Dict]:
    """
    Return the root modules for a course.
    Each module has an Id, Title, and nested Structure list (may be empty — use
    /modules/{orgUnitId}/{moduleId} to load children on demand).
    """
    token_row = await _get_valid_token(current_user.id, db)
    base = token_row.brightspace_base_url

    data = await _bs_get(
        f"{base}/d2l/api/le/{_LE_VER}/{org_unit_id}/content/root/",
        token_row.access_token,
    )

    return [
        {
            "id": m["Id"],
            "title": m["Title"],
            "type": "module",
            "isHidden": m.get("IsHidden", False),
            "childCount": len(m.get("Structure", [])),
        }
        for m in (data if isinstance(data, list) else [])
    ]


@router.get("/modules/{org_unit_id}/{module_id}")
async def list_module_structure(
    org_unit_id: int = Path(...),
    module_id: int = Path(...),
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
) -> List[Dict]:
    """
    Return the immediate children of a module.
    Each child is either a sub-module (type='module') or a topic (type='topic').
    File topics have topicType=1; links have topicType=3.
    Only file topics can be imported.
    """
    token_row = await _get_valid_token(current_user.id, db)
    base = token_row.brightspace_base_url

    data = await _bs_get(
        f"{base}/d2l/api/le/{_LE_VER}/{org_unit_id}/content/modules/{module_id}/structure/",
        token_row.access_token,
    )

    results = []
    for item in (data if isinstance(data, list) else []):
        if item.get("Type") == 0:  # sub-module
            results.append({
                "id": item["Id"],
                "title": item["Title"],
                "type": "module",
                "isHidden": item.get("IsHidden", False),
                "childCount": len(item.get("Structure", [])),
            })
        elif item.get("Type") == 1:  # topic
            topic_type = item.get("TopicType", 0)
            results.append({
                "id": item["Id"],
                "title": item["Title"],
                "type": "topic",
                "topicType": topic_type,
                "isFile": topic_type == 1,
                "isHidden": item.get("IsHidden", False),
                "url": item.get("Url"),
            })

    return results


@router.get("/topics/{org_unit_id}/{topic_id}/file")
async def proxy_topic_file(
    org_unit_id: int = Path(...),
    topic_id: int = Path(...),
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Stream the file for a Brightspace topic back to the browser.

    The frontend receives this as a Blob, wraps it in a File object, and submits
    it to the existing upload endpoint (knowledge documents, reference solutions,
    course materials, or session creation) exactly as if the user had chosen a
    local file — no changes to existing upload endpoints required.
    """
    token_row = await _get_valid_token(current_user.id, db)
    base = token_row.brightspace_base_url

    url = f"{base}/d2l/api/le/{_LE_VER}/{org_unit_id}/content/topics/{topic_id}/file"

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        bs_resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {token_row.access_token}"},
        )

    if bs_resp.status_code == 403:
        raise HTTPException(status_code=403, detail="Brightspace denied file access. Check your account permissions.")
    if bs_resp.status_code == 404:
        raise HTTPException(status_code=404, detail="File not found in Brightspace.")
    if not bs_resp.is_success:
        raise HTTPException(status_code=502, detail=f"Brightspace returned {bs_resp.status_code} when fetching file.")

    content_type = bs_resp.headers.get("content-type", "application/octet-stream")
    content_disposition = bs_resp.headers.get(
        "content-disposition",
        f"attachment; filename=\"brightspace_topic_{topic_id}\"",
    )

    return StreamingResponse(
        iter([bs_resp.content]),
        media_type=content_type,
        headers={
            "Content-Disposition": content_disposition,
            "X-Brightspace-Topic-Id": str(topic_id),
            "X-Brightspace-Org-Unit-Id": str(org_unit_id),
        },
    )
