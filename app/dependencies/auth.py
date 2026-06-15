import logging
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.config import settings
from app.database.connection import get_db
from app.services.auth_service import AuthService
from app.database.models import User

logger = logging.getLogger(__name__)

# Required auth: raises 403 immediately when no Authorization header is present.
security = HTTPBearer()

# Optional auth: returns None instead of raising when no Authorization header is
# present.  Use this on endpoints that legitimately serve both authenticated
# callers and anonymous callers (e.g. shared-link / guest flows).
optional_security = HTTPBearer(auto_error=False)

auth_service = AuthService()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token. Raises 401/403 if missing or invalid."""
    token = credentials.credentials

    payload = auth_service.verify_token(token)
    user_id = payload.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = await auth_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Resolve the caller as a User when an Authorization header is present,
    or return None when the request is unauthenticated.

    Never raises — callers decide how to handle an anonymous identity.
    """
    if not credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


async def require_admin(
    current_user: User = Depends(get_current_user),
    x_admin_secret: Optional[str] = Header(None, alias="X-Admin-Secret"),
) -> User:
    """
    Require admin role AND the X-Admin-Secret header (when ADMIN_SECRET is configured).

    Gate 1 — role: user must have role == "admin".
    Gate 2 — secret: when settings.admin_secret is set, the X-Admin-Secret request
              header must match it (constant-time comparison to prevent timing attacks).

    If ADMIN_SECRET is empty (dev / CI environments), gate 2 is bypassed with a
    logged warning. This allows local development without secret management while
    guaranteeing the gate is active in production.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    configured_secret = settings.admin_secret
    if configured_secret:
        if not x_admin_secret or not secrets.compare_digest(
            configured_secret, x_admin_secret
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin secret header required",
            )
    else:
        logger.warning(
            "ADMIN_SECRET is not configured — X-Admin-Secret header enforcement is "
            "disabled. Set ADMIN_SECRET before deploying to production."
        )

    return current_user


async def require_publisher(
    current_user: User = Depends(get_current_user)
) -> User:
    """Require the authenticated user to be a publisher or admin"""
    if current_user.role not in ("admin", "publisher"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Publisher access required"
        )
    return current_user


async def require_subscriber(
    current_user: User = Depends(get_current_user)
) -> User:
    """Require the authenticated user to have any valid platform role"""
    if current_user.role not in ("admin", "publisher", "subscriber"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Valid platform role required"
        )
    return current_user