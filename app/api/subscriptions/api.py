"""
Avatar subscription endpoints.

Routes (all under /api/subscriber):
  POST   /api/subscriber/avatars/{avatar_id}/subscribe         — subscribe (checks credits)
  DELETE /api/subscriber/avatars/{avatar_id}/subscribe         — unsubscribe
  GET    /api/subscriber/avatars                               — list own subscriptions
  GET    /api/subscriber/avatars/{avatar_id}/subscription-status — check subscription

RBAC:
  subscriber  — subscribe/unsubscribe own; list own
  admin       — unsubscribe any; list all (optionally filtered by subscriber_id)
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Avatar, AvatarSubscription, CreditBalance, User
from app.dependencies.auth import get_current_user, require_subscriber
from app.schemas.schemas import (
    SubscriptionListResponse,
    SubscriptionResponse,
    SubscriptionStatusResponse,
)
from app.services import billing_service, enrollment_service
from app.services.subscription_service import subscription_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscriber", tags=["subscriptions"])


@router.post(
    "/avatars/{avatar_id}/subscribe",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def subscribe(
    avatar_id: UUID,
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """
    Subscribe the authenticated user to a published avatar.

    - Only subscribers may call this endpoint.
    - The avatar must be published (is_published=True).
    - If the avatar has a subscription_cost > 0, credits are deducted atomically.
    - Returns 402 if the subscriber lacks sufficient credits.
    - Returns 409 if already subscribed.
    """
    try:
        # Load avatar to check cost before delegating to service
        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        if not avatar.is_published:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Avatar is not published and cannot be subscribed to",
            )

        cost = Decimal(str(avatar.subscription_cost)) if avatar.subscription_cost else Decimal("0")

        if cost > 0:
            balance_info = billing_service.get_active_balance(current_user.id, db)
            available = balance_info["balance"]
            if available < cost:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail={
                        "error": "insufficient_credits",
                        "required": float(cost),
                        "available": float(available),
                        "message": "Not enough credits. Redeem an access code to continue.",
                    },
                )
            # Deduct credits atomically
            funded_by = balance_info["source"]
            if funded_by == "access_code":
                from app.database.models import AccessCode
                ac = (
                    db.query(AccessCode)
                    .filter(AccessCode.id == balance_info["access_code_id"])
                    .with_for_update()
                    .first()
                )
                ac.remaining_credits = Decimal(str(ac.remaining_credits)) - cost
                ac.updated_at = datetime.utcnow()
            else:
                cb = (
                    db.query(CreditBalance)
                    .filter(CreditBalance.user_id == current_user.id)
                    .with_for_update()
                    .first()
                )
                cb.balance_credits = Decimal(str(cb.balance_credits)) - cost
                cb.updated_at = datetime.utcnow()
            db.flush()

        sub = subscription_service.subscribe(db, current_user, str(avatar_id))

        # Auto-enroll in linked courses and programs (R51, R18, R57)
        try:
            enrollment_service.enroll_from_avatar(current_user.id, avatar_id, db)
            db.commit()
        except Exception as enroll_exc:
            logger.warning(
                "Enrollment failed after subscription for user %s, avatar %s: %s",
                current_user.id,
                avatar_id,
                enroll_exc,
            )

        return sub
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ subscribe error: {e}")
        raise HTTPException(status_code=500, detail=f"Subscription failed: {e}")


@router.delete(
    "/avatars/{avatar_id}/subscribe",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unsubscribe(
    avatar_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Remove a subscription.

    - Subscribers may only remove their own subscription.
    - Admins may remove any subscription.
    - Returns 404 if the subscription does not exist.
    """
    try:
        subscription_service.unsubscribe(db, current_user, str(avatar_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ unsubscribe error: {e}")
        raise HTTPException(status_code=500, detail=f"Unsubscribe failed: {e}")


@router.get(
    "/avatars",
    response_model=SubscriptionListResponse,
)
def list_subscriptions(
    subscriber_id: Optional[UUID] = Query(
        None,
        description="Admin only — filter by subscriber UUID. Ignored for non-admin callers.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List avatar subscriptions.

    - Subscribers receive only their own subscriptions (subscriber_id param is ignored).
    - Admins may pass subscriber_id to filter; omitting it returns all subscriptions.
    """
    if current_user.role not in ("subscriber", "admin", "publisher"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    try:
        subs = subscription_service.list_subscriptions(
            db,
            caller=current_user,
            subscriber_id=str(subscriber_id) if subscriber_id else None,
        )
        return SubscriptionListResponse(
            subscriptions=subs,
            total=len(subs),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ list_subscriptions error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list subscriptions: {e}")


@router.get(
    "/avatars/{avatar_id}/subscription-status",
    response_model=SubscriptionStatusResponse,
)
def subscription_status(
    avatar_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Check whether the authenticated user has an active subscription to an avatar.
    Automatically deactivates expired subscriptions on read.
    """
    try:
        sub = (
            db.query(AvatarSubscription)
            .filter(
                AvatarSubscription.subscriber_id == current_user.id,
                AvatarSubscription.avatar_id == avatar_id,
            )
            .first()
        )

        if sub and sub.is_active and sub.expires_at and sub.expires_at < datetime.utcnow():
            sub.is_active = False
            db.commit()
            db.refresh(sub)

        active_sub = sub if (sub and sub.is_active) else None
        return SubscriptionStatusResponse(
            subscribed=active_sub is not None,
            subscription=active_sub,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ subscription_status error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check subscription status: {e}")
