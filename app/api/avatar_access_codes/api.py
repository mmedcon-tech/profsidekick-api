"""W3: Avatar access code API.

Publisher routes (under /api/publisher/avatars/{avatar_id}/access-codes):
  GET    /                   — list codes for an avatar
  POST   /                   — create a new code
  PATCH  /{code_id}          — update max_users or deactivate
  DELETE /{code_id}          — deactivate (soft)

Subscriber route (under /api/avatar-access-codes):
  POST   /redeem             — redeem a code → subscription + enrollment + optional credits
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Avatar, User
from app.dependencies.auth import get_current_user, require_publisher, require_subscriber
from app.schemas.schemas import (
    AvatarAccessCodeCreate,
    AvatarAccessCodeResponse,
    AvatarAccessCodesListResponse,
    AvatarAccessCodeUpdate,
    AvatarCodeRedeemRequest,
    AvatarCodeRedeemResponse,
)
from app.services import avatar_access_code_service

publisher_router = APIRouter(
    prefix="/api/publisher/avatars/{avatar_id}/access-codes",
    tags=["avatar-access-codes"],
)

subscriber_router = APIRouter(
    prefix="/api/avatar-access-codes",
    tags=["avatar-access-codes"],
)


# ── Ownership helper ──────────────────────────────────────────────────────────


def _get_avatar_and_assert_ownership(
    avatar_id: UUID, current_user: User, db: Session
) -> Avatar:
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found"
        )
    if current_user.role != "admin" and str(avatar.publisher_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this avatar"
        )
    return avatar


# ── Publisher: code management (R49) ─────────────────────────────────────────


@publisher_router.get("", response_model=AvatarAccessCodesListResponse)
def list_access_codes(
    avatar_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    """List all access codes for an avatar."""
    _get_avatar_and_assert_ownership(avatar_id, current_user, db)
    codes = avatar_access_code_service.list_codes(avatar_id, db)
    return AvatarAccessCodesListResponse(
        codes=[AvatarAccessCodeResponse.model_validate(c) for c in codes],
        total=len(codes),
    )


@publisher_router.post(
    "", response_model=AvatarAccessCodeResponse, status_code=status.HTTP_201_CREATED
)
def create_access_code(
    avatar_id: UUID,
    body: AvatarAccessCodeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    """Create a new avatar access code.
    The code will allow up to max_users subscribers to redeem it."""
    code = avatar_access_code_service.create_code(
        avatar_id=avatar_id,
        publisher_id=current_user.id,
        max_users=body.max_users,
        db=db,
        credits_per_user=body.credits_per_user,
        expires_at=body.expires_at,
    )
    return AvatarAccessCodeResponse.model_validate(code)


@publisher_router.patch("/{code_id}", response_model=AvatarAccessCodeResponse)
def update_access_code(
    avatar_id: UUID,
    code_id: UUID,
    body: AvatarAccessCodeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    """Update max_users or toggle is_active on an avatar access code.
    max_users cannot be set below the current redemption count."""
    code = avatar_access_code_service.update_code(
        code_id=code_id,
        avatar_id=avatar_id,
        publisher_id=current_user.id,
        db=db,
        requester_role=current_user.role,
        max_users=body.max_users,
        is_active=body.is_active,
    )
    return AvatarAccessCodeResponse.model_validate(code)


@publisher_router.delete("/{code_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_access_code(
    avatar_id: UUID,
    code_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    """Deactivate an avatar access code. Existing redemptions are unaffected."""
    avatar_access_code_service.deactivate_code(
        code_id=code_id,
        avatar_id=avatar_id,
        publisher_id=current_user.id,
        db=db,
        requester_role=current_user.role,
    )


# ── Subscriber: redemption (R48) ──────────────────────────────────────────────


@subscriber_router.post("/redeem", response_model=AvatarCodeRedeemResponse)
def redeem_avatar_access_code(
    body: AvatarCodeRedeemRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_subscriber),
):
    """Redeem an avatar access code.

    On success atomically:
    - Creates an avatar subscription (idempotent — skipped if already subscribed).
    - Enrolls the subscriber in all courses linked to the avatar.
    - Enrolls the subscriber in all programs that include the avatar.
    - Grants credits if the code has credits_per_user > 0.
    """
    result = avatar_access_code_service.redeem_code(body.code, current_user, db)

    courses_msg = (
        f" Enrolled in {len(result['courses_enrolled'])} course(s)."
        if result["courses_enrolled"]
        else ""
    )
    programs_msg = (
        f" Added to {len(result['programs_enrolled'])} program(s)."
        if result["programs_enrolled"]
        else ""
    )
    credits_msg = (
        f" {result['credits_granted']} credits granted."
        if result["credits_granted"] > 0
        else ""
    )

    return AvatarCodeRedeemResponse(
        success=True,
        code=result["code"],
        avatar_id=result["avatar_id"],
        subscription_created=result["subscription_created"],
        credits_granted=result["credits_granted"],
        courses_enrolled=result["courses_enrolled"],
        programs_enrolled=result["programs_enrolled"],
        message=f"Access code redeemed successfully.{courses_msg}{programs_msg}{credits_msg}",
    )
