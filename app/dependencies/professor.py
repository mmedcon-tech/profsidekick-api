from fastapi import Depends, HTTPException, status

from app.database.models import User
from app.dependencies.auth import get_current_user

# Roles that may access publisher/persona endpoints (legacy + current).
_ALLOWED_ROLES = frozenset({"publisher", "admin", "professor", "teacher"})


async def require_professor(
    current_user: User = Depends(get_current_user),
) -> User:
    """Only publishers (and admins) may access persona endpoints."""
    if current_user.role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Publisher access required",
        )
    return current_user
