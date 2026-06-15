"""W6 (Phase 6): Analytics API endpoints (R101, R102, R103, R119).

Routes:
  GET /api/subscriber/analytics   — subscriber progress and assessment data
  GET /api/publisher/analytics    — publisher avatar and course performance
  GET /api/admin/analytics        — platform-wide metrics
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import get_current_user
from app.services import analytics_service
from app.schemas.schemas import (
    SubscriberAnalyticsResponse,
    PublisherAnalyticsResponse,
    AdminAnalyticsResponse,
)

router = APIRouter(prefix="/api", tags=["analytics"])


def _require_subscriber(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("subscriber", "publisher", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Subscriber access required")
    return current_user


def _require_publisher(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("publisher", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Publisher access required")
    return current_user


def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


@router.get("/subscriber/analytics", response_model=SubscriberAnalyticsResponse)
def get_subscriber_analytics(
    current_user: User = Depends(_require_subscriber),
    db: Session = Depends(get_db),
):
    """Return course progress, time spent, assessment scores, and ratings for the requesting subscriber (R101)."""
    data = analytics_service.get_subscriber_analytics(user_id=current_user.id, db=db)
    return SubscriberAnalyticsResponse(**data)


@router.get("/publisher/analytics", response_model=PublisherAnalyticsResponse)
def get_publisher_analytics(
    current_user: User = Depends(_require_publisher),
    db: Session = Depends(get_db),
):
    """Return per-avatar and per-course performance metrics for the requesting publisher (R102)."""
    data = analytics_service.get_publisher_analytics(publisher_id=current_user.id, db=db)
    return PublisherAnalyticsResponse(**data)


@router.get("/admin/analytics", response_model=AdminAnalyticsResponse)
def get_admin_analytics(
    current_user: User = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Return platform-wide usage and revenue metrics for admins (R103, R119)."""
    data = analytics_service.get_admin_analytics(db=db)
    return AdminAnalyticsResponse(**data)
