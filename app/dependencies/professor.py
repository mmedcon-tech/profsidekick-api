from fastapi import Depends, HTTPException, status

from app.database.models import User
from app.dependencies.auth import get_current_user


async def require_professor(
    current_user: User = Depends(get_current_user),
) -> User:
    """Only professors may access persona endpoints."""
    if current_user.role == "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Professor access required",
        )
    return current_user
