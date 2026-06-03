"""
Avatar subscription endpoints.

Routes (all under /api/subscriber):
  POST   /api/subscriber/avatars/{avatar_id}/subscribe    — subscribe
  DELETE /api/subscriber/avatars/{avatar_id}/subscribe    — unsubscribe
  GET    /api/subscriber/avatars                          — list own subscriptions

RBAC:
  subscriber  — subscribe/unsubscribe own; list own
  admin       — unsubscribe any; list all (optionally filtered by subscriber_id)
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import get_current_user, require_subscriber
from app.schemas.schemas import SubscriptionListResponse, SubscriptionResponse
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

    - Only subscribers and admins may call this endpoint.
    - The avatar must be published (is_published=True).
    - Returns 409 if already subscribed.
    """
    try:
        sub = subscription_service.subscribe(db, current_user, str(avatar_id))
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
