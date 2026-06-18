"""W3: Avatar access code service (R46, R47, R48, R49).

Publishers create codes scoped to a specific avatar.
Subscribers redeem a code to receive atomically:
  - An avatar subscription (idempotent — skipped if already subscribed)
  - Enrollment in all courses linked to the avatar (via avatar_courses)
  - Enrollment in all programs that include the avatar (via program_avatars)
  - Optional credit grant (if credits_per_user > 0)
"""

import logging
import random
import string
import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import Avatar, AvatarSubscription, CreditBalance, User
from app.database.models.avatar_access_codes import AvatarAccessCode, AvatarAccessCodeRedemption
from app.services import enrollment_service

logger = logging.getLogger(__name__)


def _generate_code() -> str:
    chars = string.ascii_uppercase + string.digits
    groups = ["".join(random.choices(chars, k=4)) for _ in range(3)]
    return "-".join(groups)


# ── Publisher CRUD (R49) ──────────────────────────────────────────────────────


def list_codes(avatar_id: UUID, db: Session) -> List[AvatarAccessCode]:
    return (
        db.query(AvatarAccessCode)
        .filter(AvatarAccessCode.avatar_id == avatar_id)
        .order_by(AvatarAccessCode.created_at.desc())
        .all()
    )


def get_code(code_id: UUID, db: Session) -> AvatarAccessCode:
    code = db.query(AvatarAccessCode).filter(AvatarAccessCode.id == code_id).first()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Access code not found"
        )
    return code


def create_code(
    avatar_id: UUID,
    publisher_id: UUID,
    max_users: int,
    db: Session,
    credits_per_user: Decimal = Decimal("0"),
    expires_at: Optional[datetime] = None,
) -> AvatarAccessCode:
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found"
        )
    if str(avatar.publisher_id) != str(publisher_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this avatar"
        )

    # Deduct total credits from publisher balance upfront (publisher_id owns the credits)
    total_credits = Decimal(str(credits_per_user)) * max_users
    if total_credits > 0:
        balance = (
            db.query(CreditBalance)
            .filter(CreditBalance.user_id == publisher_id)
            .with_for_update()
            .first()
        )
        available = Decimal(str(balance.balance_credits)) if balance else Decimal("0")
        if available < total_credits:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Insufficient credits. Need {total_credits}, have {available}. "
                    "Add more credits before generating this code."
                ),
            )
        if balance:
            balance.balance_credits = available - total_credits
            balance.updated_at = datetime.utcnow()

    # Collision-safe code generation (10 retries)
    code_str: Optional[str] = None
    for _ in range(10):
        candidate = _generate_code()
        if not db.query(AvatarAccessCode).filter(AvatarAccessCode.code == candidate).first():
            code_str = candidate
            break
    if not code_str:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate a unique access code. Please try again.",
        )

    code = AvatarAccessCode(
        id=uuid.uuid4(),
        avatar_id=avatar_id,
        created_by=publisher_id,
        code=code_str,
        max_users=max_users,
        users_count=0,
        credits_per_user=credits_per_user,
        is_active=True,
        expires_at=expires_at,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(code)
    db.commit()
    db.refresh(code)
    return code


def update_code(
    code_id: UUID,
    avatar_id: UUID,
    publisher_id: UUID,
    db: Session,
    requester_role: str = "publisher",
    max_users: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> AvatarAccessCode:
    code = get_code(code_id, db)
    _assert_code_ownership(code, avatar_id, publisher_id, requester_role)

    if max_users is not None:
        if max_users < code.users_count:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"max_users cannot be less than current redemption count ({code.users_count})"
                ),
            )
        code.max_users = max_users
    if is_active is not None:
        code.is_active = is_active

    code.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(code)
    return code


def deactivate_code(
    code_id: UUID,
    avatar_id: UUID,
    publisher_id: UUID,
    db: Session,
    requester_role: str = "publisher",
) -> None:
    code = get_code(code_id, db)
    _assert_code_ownership(code, avatar_id, publisher_id, requester_role)
    code.is_active = False
    code.updated_at = datetime.utcnow()
    db.commit()


# ── Subscriber redemption (R48) ───────────────────────────────────────────────


def redeem_code(code_str: str, subscriber: User, db: Session) -> dict:
    """
    Redeem an avatar access code.

    Raises HTTP 404 if the code does not exist in avatar_access_codes.
    Use try_redeem_avatar_code() from the unified billing endpoint instead
    when detection is needed before raising 404.

    Atomically:
    1. Validate code (active, not expired, capacity available).
    2. Reject duplicate redemption (409).
    3. Create avatar subscription if not already subscribed.
    4. Enroll subscriber in all linked courses and programs.
    5. Grant credits if credits_per_user > 0.
    6. Record redemption row + increment users_count.
    7. Single db.commit().
    """
    code_upper = code_str.strip().upper()
    code = db.query(AvatarAccessCode).filter(AvatarAccessCode.code == code_upper).first()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Avatar access code not found",
        )
    return _execute_redemption(code, subscriber, db)


def try_redeem_avatar_code(code_str: str, subscriber: User, db: Session) -> Optional[dict]:
    """
    Attempt to redeem an avatar access code.

    Returns None if the code does not exist in avatar_access_codes (so the
    caller can fall through to the regular billing code flow).
    Raises HTTP exceptions for invalid/expired/exhausted/duplicate codes.
    """
    code_upper = code_str.strip().upper()
    code = db.query(AvatarAccessCode).filter(AvatarAccessCode.code == code_upper).first()
    if not code:
        return None
    return _execute_redemption(code, subscriber, db)


def _execute_redemption(code: AvatarAccessCode, subscriber: User, db: Session) -> dict:
    # Re-fetch with SELECT FOR UPDATE to close the TOCTOU race on capacity (EH-01 fix).
    # Without this, two concurrent requests can both read users_count < max_users and
    # both proceed to increment, exceeding the limit.
    code = (
        db.query(AvatarAccessCode)
        .filter(AvatarAccessCode.id == code.id)
        .with_for_update()
        .first()
    )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Avatar access code not found",
        )
    _validate_code(code)

    existing_redemption = (
        db.query(AvatarAccessCodeRedemption)
        .filter(
            AvatarAccessCodeRedemption.user_id == subscriber.id,
            AvatarAccessCodeRedemption.avatar_access_code_id == code.id,
        )
        .first()
    )
    if existing_redemption:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already redeemed this access code",
        )

    avatar = db.query(Avatar).filter(Avatar.id == code.avatar_id).first()
    if not avatar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Avatar linked to this code no longer exists",
        )

    # Create subscription (skip if already subscribed — idempotent)
    existing_sub = (
        db.query(AvatarSubscription)
        .filter(
            AvatarSubscription.subscriber_id == subscriber.id,
            AvatarSubscription.avatar_id == code.avatar_id,
        )
        .first()
    )
    subscription_created = False
    if not existing_sub:
        db.add(
            AvatarSubscription(
                id=uuid.uuid4(),
                subscriber_id=subscriber.id,
                avatar_id=code.avatar_id,
                subscribed_at=datetime.utcnow(),
                is_active=True,
            )
        )
        subscription_created = True

    # Enroll in linked courses and programs (R51, R18)
    enrollment_result = enrollment_service.enroll_from_avatar(
        subscriber.id, code.avatar_id, db
    )

    # Grant credits (R48, optional)
    credits_granted = Decimal("0")
    if code.credits_per_user and Decimal(str(code.credits_per_user)) > 0:
        credits_granted = Decimal(str(code.credits_per_user))
        balance = (
            db.query(CreditBalance)
            .filter(CreditBalance.user_id == subscriber.id)
            .with_for_update()
            .first()
        )
        if balance:
            balance.balance_credits = Decimal(str(balance.balance_credits)) + credits_granted
            balance.updated_at = datetime.utcnow()
        else:
            db.add(
                CreditBalance(
                    id=uuid.uuid4(),
                    user_id=subscriber.id,
                    balance_credits=credits_granted,
                    updated_at=datetime.utcnow(),
                )
            )

    # Record redemption + increment counter
    db.add(
        AvatarAccessCodeRedemption(
            id=uuid.uuid4(),
            avatar_access_code_id=code.id,
            user_id=subscriber.id,
            redeemed_at=datetime.utcnow(),
            credits_granted=credits_granted,
        )
    )
    code.users_count += 1
    code.updated_at = datetime.utcnow()

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Redemption conflict — please try again.",
        )

    logger.info(
        "Avatar access code %s redeemed by user %s — subscription_created=%s, "
        "courses=%d, programs=%d, credits=%s",
        code.code,
        subscriber.id,
        subscription_created,
        len(enrollment_result["courses_enrolled"]),
        len(enrollment_result["programs_enrolled"]),
        credits_granted,
    )
    return {
        "code": code.code,
        "avatar_id": code.avatar_id,
        "subscription_created": subscription_created,
        "credits_granted": credits_granted,
        "courses_enrolled": enrollment_result["courses_enrolled"],
        "programs_enrolled": enrollment_result["programs_enrolled"],
    }


# ── Internal helpers ──────────────────────────────────────────────────────────


def _validate_code(code: AvatarAccessCode) -> None:
    if not code.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This access code is no longer active",
        )
    if code.expires_at and code.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This access code has expired",
        )
    if code.users_count >= code.max_users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This access code has reached its user limit",
        )


def _assert_code_ownership(
    code: AvatarAccessCode,
    avatar_id: UUID,
    publisher_id: UUID,
    requester_role: str = "publisher",
) -> None:
    if str(code.avatar_id) != str(avatar_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access code not found for this avatar",
        )
    if requester_role != "admin" and str(code.created_by) != str(publisher_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this access code",
        )
