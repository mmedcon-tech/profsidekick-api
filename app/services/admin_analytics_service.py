from collections import Counter
from datetime import datetime

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database.models import (
    Avatar,
    Course,
    CourseStudent,
    Session as TeachingSession,
    SessionRun,
    SessionRunStatus,
    UsageRecord,
    User,
)


def get_admin_analytics(db: Session) -> dict:
    role_counts = dict(
        db.query(User.role, func.count(User.id)).group_by(User.role).all()
    )
    course_count = db.query(func.count(Course.id)).filter(
        Course.is_deleted.is_(False)
    ).scalar() or 0
    avatar_count = db.query(func.count(Avatar.id)).scalar() or 0
    run_count = db.query(func.count(SessionRun.id)).scalar() or 0
    credits_consumed = db.query(
        func.coalesce(func.sum(UsageRecord.credits_charged), 0)
    ).scalar()

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    active_sessions_today = (
        db.query(func.count(SessionRun.id))
        .filter(
            SessionRun.status == SessionRunStatus.ACTIVE,
            SessionRun.start_time >= today,
        )
        .scalar()
        or 0
    )

    now = datetime.utcnow()
    current_month = datetime(now.year, now.month, 1)
    first_month = current_month
    for _ in range(5):
        if first_month.month == 1:
            first_month = datetime(first_month.year - 1, 12, 1)
        else:
            first_month = datetime(first_month.year, first_month.month - 1, 1)

    completed_runs = (
        db.query(SessionRun.end_time)
        .filter(
            SessionRun.status == SessionRunStatus.COMPLETED,
            SessionRun.end_time >= first_month,
            SessionRun.end_time <= now,
        )
        .all()
    )
    completions_by_month = Counter(
        (end_time.year, end_time.month)
        for (end_time,) in completed_runs
        if end_time is not None
    )
    monthly_completions = []
    month = first_month
    for _ in range(6):
        monthly_completions.append({
            "month": month.strftime("%b %Y"),
            "value": completions_by_month[(month.year, month.month)],
        })
        if month.month == 12:
            month = datetime(month.year + 1, 1, 1)
        else:
            month = datetime(month.year, month.month + 1, 1)

    enrolled_by_course = dict(
        db.query(CourseStudent.course_id, func.count(CourseStudent.id))
        .group_by(CourseStudent.course_id)
        .all()
    )
    course_run_rows = (
        db.query(
            TeachingSession.course_id,
            func.count(SessionRun.id),
            func.sum(
                case(
                    (SessionRun.status == SessionRunStatus.COMPLETED, 1),
                    else_=0,
                )
            ),
        )
        .join(SessionRun, SessionRun.session_id == TeachingSession.id)
        .group_by(TeachingSession.course_id)
        .all()
    )
    runs_by_course = {
        course_id: (int(total_runs), int(completed_runs or 0))
        for course_id, total_runs, completed_runs in course_run_rows
    }
    courses = (
        db.query(Course)
        .filter(Course.is_deleted.is_(False))
        .order_by(Course.name)
        .all()
    )
    course_performance = []
    for course in courses:
        total_runs, completed_runs = runs_by_course.get(course.id, (0, 0))
        course_performance.append({
            "name": course.name or "Untitled course",
            "completion": round(completed_runs * 100 / total_runs) if total_runs else 0,
            "subscribers": int(enrolled_by_course.get(course.id, 0)),
        })

    return {
        "total_users": sum(role_counts.values()),
        "total_publishers": int(role_counts.get("publisher", 0)),
        "total_subscribers": int(role_counts.get("subscriber", 0)),
        "total_programs": 0,
        "total_courses": int(course_count),
        "total_avatars": int(avatar_count),
        "total_session_runs": int(run_count),
        "total_credits_consumed": float(credits_consumed or 0),
        "system_health": 100,
        "active_sessions_today": int(active_sessions_today),
        "monthly_completions": monthly_completions,
        "course_performance": course_performance,
        "at_risk_learners": [],
    }
