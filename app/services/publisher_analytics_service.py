"""
Publisher dashboard summary (v2 §9.2): GET /api/publisher/analytics/summary.

Only the publisher's own twins, courses and sessions. Figures that the
platform does not record yet (consultation goals, review submissions,
escalations) are returned as None, never as a made-up zero, so the UI can say
"not tracked yet".

At-risk rule (v2 §9.2). Implemented now: a member enrolled in one of the
publisher's active courses who has not started a session in 14 days (counted
from enrolment when they never started one). Added with phase 4: fewer than
half the milestones after two sessions, and an escalation open over 24 hours.
Guests share one user row, so they are never counted as individual members.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database.models import Avatar, Course, CourseStudent, SessionRun, User
from app.database.models import Session as SessionModel

INACTIVE_DAYS = 14
ACTIVE_WINDOW_DAYS = 30
AT_RISK_LIMIT = 20
RULES_EVALUATED = ["inactive_14_days"]
RULES_PENDING = ["milestones_under_half_after_two_sessions", "escalation_open_24h"]


def _excluded_users(publisher_id, guest_user_uuid: Optional[str]) -> list:
    excluded = [publisher_id]
    if guest_user_uuid:
        excluded.append(guest_user_uuid)
    return excluded


def build_publisher_summary(
    db: Session,
    publisher_id,
    *,
    now: Optional[datetime] = None,
    guest_user_uuid: Optional[str] = None,
) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    excluded = _excluded_users(publisher_id, guest_user_uuid)

    avatars = (
        db.query(Avatar.id, Avatar.is_published)
        .filter(Avatar.publisher_id == publisher_id)
        .all()
    )
    avatar_ids = [a.id for a in avatars]
    published = sum(1 for a in avatars if a.is_published)

    courses = (
        db.query(Course)
        .filter(Course.user_id == publisher_id, Course.is_deleted.isnot(True))
        .all()
    )
    course_ids = [c.id for c in courses]

    scope = [SessionModel.user_id == publisher_id]
    if avatar_ids:
        scope.append(SessionModel.avatar_id.in_(avatar_ids))
    if course_ids:
        scope.append(SessionModel.course_id.in_(course_ids))
    session_ids = [
        row.id for row in db.query(SessionModel.id).filter(or_(*scope)).all()
    ]

    runs = (
        db.query(SessionRun).filter(SessionRun.session_id.in_(session_ids))
        if session_ids
        else None
    )

    active_members = 0
    sessions_this_month = 0
    minutes_this_month = 0
    if runs is not None:
        active_members = (
            runs.filter(
                SessionRun.start_time >= now - timedelta(days=ACTIVE_WINDOW_DAYS),
                SessionRun.user_id.notin_(excluded),
            )
            .with_entities(func.count(func.distinct(SessionRun.user_id)))
            .scalar()
            or 0
        )
        month_runs = runs.filter(SessionRun.start_time >= month_start).all()
        sessions_this_month = len(month_runs)
        minutes_this_month = int(
            sum(
                (r.end_time - r.start_time).total_seconds()
                for r in month_runs
                if r.end_time and r.start_time and r.end_time > r.start_time
            )
            // 60
        )

    return {
        "twins": {"draft": len(avatars) - published, "published": published},
        "active_members_30d": active_members,
        "sessions_this_month": sessions_this_month,
        "minutes_this_month": minutes_this_month,
        # Not recorded by the platform yet (phases 4 and 6).
        "average_goal_completion": None,
        "review_submissions": None,
        "open_escalations": None,
        "at_risk": _at_risk(db, courses, session_ids, excluded, now),
        "at_risk_rules_evaluated": RULES_EVALUATED,
        "at_risk_rules_pending": RULES_PENDING,
    }


def _at_risk(
    db: Session, courses, session_ids, excluded, now: datetime
) -> List[Dict[str, Any]]:
    active_courses = {c.id: c for c in courses if c.is_active is not False}
    if not active_courses:
        return []

    enrolments = (
        db.query(CourseStudent, User)
        .join(User, User.id == CourseStudent.user_id)
        .filter(
            CourseStudent.course_id.in_(list(active_courses)),
            CourseStudent.user_id.notin_(excluded),
        )
        .all()
    )

    # Latest run per (member, course) on that course's sessions.
    last_run: Dict[tuple, datetime] = {}
    if session_ids:
        rows = (
            db.query(
                SessionRun.user_id,
                SessionModel.course_id,
                func.max(SessionRun.start_time),
            )
            .join(SessionModel, SessionModel.id == SessionRun.session_id)
            .filter(SessionModel.course_id.in_(list(active_courses)))
            .group_by(SessionRun.user_id, SessionModel.course_id)
            .all()
        )
        last_run = {(r[0], r[1]): r[2] for r in rows}

    cutoff = now - timedelta(days=INACTIVE_DAYS)
    flagged = []
    for enrolment, user in enrolments:
        last = last_run.get((enrolment.user_id, enrolment.course_id))
        since = last or enrolment.enrollment_date
        if since is None or since > cutoff:
            continue
        days = (now - since).days
        course = active_courses[enrolment.course_id]
        flagged.append(
            {
                "member_id": str(user.id),
                "member_name": " ".join(
                    p for p in (user.first_name, user.last_name) if p
                )
                or user.username,
                "course_id": course.course_id,
                "course_name": course.name,
                "days_inactive": days,
                "reason": (
                    f"No session in {days} days"
                    if last
                    else f"Enrolled {days} days ago and has not started a session"
                ),
                "action": "open_course",
            }
        )
    flagged.sort(key=lambda f: f["days_inactive"], reverse=True)
    return flagged[:AT_RISK_LIMIT]
