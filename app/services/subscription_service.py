"""
Avatar subscription service.

Enforces access control for subscribe / unsubscribe / list operations.

Rules:
  - Only subscribers (and admins) can subscribe.
  - Only published avatars may be subscribed to.
  - A subscriber can only remove their own subscription; admins may remove any.
  - Duplicate subscriptions are rejected (DB unique constraint is the final gate;
    the service check provides a clear error before hitting the DB).
"""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import Avatar, AvatarSubscription, User


class SubscriptionService:

    def subscribe(
        self,
        db: Session,
        subscriber: User,
        avatar_id: str,
    ) -> AvatarSubscription:
        """
        Subscribe subscriber to a published avatar.
        Raises 404 if the avatar is not found or not published.
        Raises 409 if the subscription already exists.
        """
        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Avatar not found",
            )
        if not avatar.is_published:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Avatar is not published and cannot be subscribed to",
            )

        existing = (
            db.query(AvatarSubscription)
            .filter(
                AvatarSubscription.subscriber_id == subscriber.id,
                AvatarSubscription.avatar_id == avatar_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Already subscribed to this avatar",
            )

        sub = AvatarSubscription(
            id=uuid.uuid4(),
            subscriber_id=subscriber.id,
            avatar_id=avatar_id,
            subscribed_at=datetime.utcnow(),
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
        return sub

    def unsubscribe(
        self,
        db: Session,
        caller: User,
        avatar_id: str,
    ) -> None:
        """
        Remove a subscription.
        Subscribers may only remove their own subscription.
        Admins may remove any subscription.
        Raises 404 if the subscription does not exist.
        """
        query = db.query(AvatarSubscription).filter(
            AvatarSubscription.avatar_id == avatar_id
        )

        if caller.role != "admin":
            query = query.filter(AvatarSubscription.subscriber_id == caller.id)

        sub = query.first()
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscription not found",
            )

        if caller.role != "admin" and str(sub.subscriber_id) != str(caller.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only remove your own subscriptions",
            )

        db.delete(sub)
        db.commit()

    def list_subscriptions(
        self,
        db: Session,
        caller: User,
        subscriber_id: Optional[str] = None,
    ) -> List[AvatarSubscription]:
        """
        List subscriptions.
        Subscribers see only their own.
        Admins may pass subscriber_id to filter; omitting it returns all subscriptions.
        """
        query = db.query(AvatarSubscription)

        if caller.role != "admin":
            query = query.filter(AvatarSubscription.subscriber_id == caller.id)
        elif subscriber_id:
            query = query.filter(AvatarSubscription.subscriber_id == subscriber_id)

        return query.order_by(AvatarSubscription.subscribed_at.desc()).all()

    def is_subscribed(
        self,
        db: Session,
        subscriber_id: str,
        avatar_id: str,
    ) -> bool:
        """Return True if a subscription exists."""
        return (
            db.query(AvatarSubscription)
            .filter(
                AvatarSubscription.subscriber_id == subscriber_id,
                AvatarSubscription.avatar_id == avatar_id,
            )
            .first()
        ) is not None


subscription_service = SubscriptionService()
