"""W4 (Phase 5): Session avatar + variant resolution service (R52).

Resolves which avatar (and its default variant) a subscriber is entitled to
use for a given session run, by walking course-linked avatars first and then
falling back to the legacy session.avatar_id field.
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.database.models import AvatarSubscription
from app.database.models.avatar_courses import AvatarCourse
from app.services.avatar_variant_service import build_variant_snapshot, resolve_default_variant

logger = logging.getLogger(__name__)


def _active_subscription(
    subscriber_id: UUID,
    avatar_id: UUID,
    now: datetime,
    db: DBSession,
) -> Optional[AvatarSubscription]:
    sub = (
        db.query(AvatarSubscription)
        .filter(
            AvatarSubscription.subscriber_id == subscriber_id,
            AvatarSubscription.avatar_id == avatar_id,
            AvatarSubscription.is_active.is_(True),
        )
        .first()
    )
    if not sub:
        return None
    if sub.expires_at and sub.expires_at < now:
        sub.is_active = False
        db.flush()
        return None
    return sub


def resolve_session_avatar(
    db_session,
    subscriber_id: UUID,
    db: DBSession,
) -> Optional[dict]:
    """Resolve avatar + default variant for a subscriber's session run.

    Resolution order:
    1. Course-linked avatars (avatar_courses WHERE course_id = session.course_id),
       ordered by sort_order. First match with an active subscription wins.
    2. Legacy fallback: session.avatar_id, if set. Logs a deprecation warning.
    3. If no avatars are linked at all → return None (no avatar requirement).
    4. If avatars exist but subscriber has no active subscription → raise 403.

    Returns:
        None  — no avatar configured for this session; subscription not required.
        dict  — {avatar_id, variant_id, variant_snapshot, source}

    Raises:
        HTTPException(403) — avatars are configured but subscriber has no
                             active subscription to any of them.
    """
    now = datetime.utcnow()

    course_linked = (
        db.query(AvatarCourse)
        .filter(AvatarCourse.course_id == db_session.course_id)
        .order_by(AvatarCourse.sort_order)
        .all()
    )

    if not course_linked and not db_session.avatar_id:
        return None

    for ac in course_linked:
        sub = _active_subscription(subscriber_id, ac.avatar_id, now, db)
        if not sub:
            continue
        variant = resolve_default_variant(ac.avatar_id, db)
        return {
            "avatar_id": ac.avatar_id,
            "variant_id": variant.id if variant else None,
            "variant_snapshot": build_variant_snapshot(variant) if variant else None,
            "source": "course_link",
        }

    if db_session.avatar_id:
        logger.warning(
            "Session %s: course-linked resolution found no active subscription. "
            "Falling back to legacy session.avatar_id=%s. "
            "Link the avatar to its course via avatar_courses to remove this fallback.",
            getattr(db_session, "session_id", db_session.id),
            db_session.avatar_id,
        )
        sub = _active_subscription(subscriber_id, db_session.avatar_id, now, db)
        if sub:
            variant = resolve_default_variant(db_session.avatar_id, db)
            return {
                "avatar_id": db_session.avatar_id,
                "variant_id": variant.id if variant else None,
                "variant_snapshot": build_variant_snapshot(variant) if variant else None,
                "source": "legacy_session_avatar_id",
            }

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have an active subscription to an avatar linked to this course.",
    )
