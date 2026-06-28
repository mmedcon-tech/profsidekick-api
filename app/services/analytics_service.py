from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, case, extract, text, select
from sqlalchemy.dialects.postgresql import JSONB

from app.database.models import (
    User, Course, Session as DbSession, SessionRun, SessionRunStatus,
    CourseStudent, Avatar, ProgramAvatar, ProgramCourse,
)

def get_subscriber_analytics(user_id: UUID, db: Session) -> Dict[str, Any]:
    # 1. Total sessions completed
    total_sessions_completed = db.query(func.count(SessionRun.id)).filter(
        SessionRun.user_id == user_id,
        SessionRun.status == SessionRunStatus.COMPLETED
    ).scalar() or 0

    # 2. Total time spent
    time_spent_query = db.query(
        func.sum(
            extract('epoch', SessionRun.end_time) - extract('epoch', SessionRun.start_time)
        )
    ).filter(
        SessionRun.user_id == user_id,
        SessionRun.status == SessionRunStatus.COMPLETED,
        SessionRun.end_time.isnot(None)
    ).scalar() or 0
    total_time_spent_sec = int(time_spent_query)

    # 3. Course Progress
    # First get all courses the student is enrolled in
    enrolled_courses = db.query(Course).join(CourseStudent).filter(
        CourseStudent.user_id == user_id,
        Course.is_deleted == False
    ).all()

    course_progress = []
    for course in enrolled_courses:
        # Total sessions in course
        total_sessions = db.query(func.count(DbSession.id)).filter(
            DbSession.course_id == course.id
        ).scalar() or 0

        # Completed sessions for this user in this course
        completed_sessions = db.query(func.count(SessionRun.id.distinct())).join(DbSession).filter(
            SessionRun.user_id == user_id,
            DbSession.course_id == course.id,
            SessionRun.status == SessionRunStatus.COMPLETED
        ).scalar() or 0

        # Time spent in this course
        c_time_spent = db.query(
            func.sum(
                extract('epoch', SessionRun.end_time) - extract('epoch', SessionRun.start_time)
            )
        ).join(DbSession).filter(
            SessionRun.user_id == user_id,
            DbSession.course_id == course.id,
            SessionRun.status == SessionRunStatus.COMPLETED,
            SessionRun.end_time.isnot(None)
        ).scalar() or 0

        # Last session at
        last_session_at = db.query(func.max(SessionRun.end_time)).join(DbSession).filter(
            SessionRun.user_id == user_id,
            DbSession.course_id == course.id,
            SessionRun.status == SessionRunStatus.COMPLETED
        ).scalar()

        completion_pct = (completed_sessions / total_sessions * 100) if total_sessions > 0 else 0.0

        course_progress.append({
            "course_id": course.id,
            "course_name": course.name or "Untitled Course",
            "completion_pct": completion_pct,
            "time_spent_sec": int(c_time_spent),
            "last_session_at": last_session_at
        })

    # 4. Recent Assessments
    # Find examination sessions
    recent_assessments_raw = db.query(
        SessionRun.id,
        SessionRun.session_run_metadata,
        SessionRun.end_time
    ).join(DbSession).filter(
        SessionRun.user_id == user_id,
        SessionRun.status == SessionRunStatus.COMPLETED,
        DbSession.session_mode == "examination",
        SessionRun.end_time.isnot(None)
    ).order_by(SessionRun.end_time.desc()).limit(10).all()

    recent_assessments = []
    total_score = 0
    score_count = 0

    for run_id, meta, end_time in recent_assessments_raw:
        meta_dict = meta if meta else {}
        score = meta_dict.get("score")
        q_count = meta_dict.get("question_count", 0)
        
        if score is not None:
            total_score += score
            score_count += 1
            
        recent_assessments.append({
            "session_run_id": run_id,
            "score": score,
            "question_count": q_count,
            "generated_at": end_time
        })

    avg_rating = (total_score / score_count) if score_count > 0 else None

    return {
        "user_id": user_id,
        "total_sessions_completed": total_sessions_completed,
        "total_time_spent_sec": total_time_spent_sec,
        "course_progress": course_progress,
        "recent_assessments": recent_assessments,
        "average_session_rating": avg_rating,
    }


def get_publisher_analytics(
    publisher_id: UUID, db: Session, program_id: Optional[UUID] = None
) -> Dict[str, Any]:
    # 1. Basic Counts — optionally scoped to a program
    avatar_q = db.query(func.count(Avatar.id)).filter(Avatar.publisher_id == publisher_id)
    course_q = db.query(func.count(Course.id)).filter(
        Course.user_id == publisher_id, Course.is_deleted == False
    )
    subscriber_q = db.query(func.count(CourseStudent.user_id.distinct())).join(Course).filter(
        Course.user_id == publisher_id, Course.is_deleted == False
    )
    sessions_q = db.query(func.count(SessionRun.id)).join(DbSession).join(Course).filter(
        Course.user_id == publisher_id, Course.is_deleted == False
    )

    if program_id:
        avatar_q = avatar_q.join(ProgramAvatar, ProgramAvatar.avatar_id == Avatar.id).filter(
            ProgramAvatar.program_id == program_id
        )
        course_q = course_q.join(ProgramCourse, ProgramCourse.course_id == Course.id).filter(
            ProgramCourse.program_id == program_id
        )
        subscriber_q = subscriber_q.join(ProgramCourse, ProgramCourse.course_id == Course.id).filter(
            ProgramCourse.program_id == program_id
        )
        sessions_q = sessions_q.join(ProgramCourse, ProgramCourse.course_id == Course.id).filter(
            ProgramCourse.program_id == program_id
        )

    total_avatars = avatar_q.scalar() or 0
    total_courses = course_q.scalar() or 0
    total_subscribers = subscriber_q.scalar() or 0
    total_sessions_run = sessions_q.scalar() or 0

    # 2. Monthly completions (past 6 months)
    import datetime
    from dateutil.relativedelta import relativedelta
    today = datetime.date.today()
    monthly_completions = []

    for i in range(5, -1, -1):
        month_date = today - relativedelta(months=i)
        start_date = month_date.replace(day=1)
        end_date = (start_date + relativedelta(months=1)) - datetime.timedelta(days=1)

        mq = db.query(func.count(SessionRun.id)).join(DbSession).join(Course).filter(
            Course.user_id == publisher_id,
            Course.is_deleted == False,
            SessionRun.status == SessionRunStatus.COMPLETED,
            SessionRun.end_time >= start_date,
            SessionRun.end_time <= end_date,
        )
        if program_id:
            mq = mq.join(ProgramCourse, ProgramCourse.course_id == Course.id).filter(
                ProgramCourse.program_id == program_id
            )
        month_count = mq.scalar() or 0
        monthly_completions.append({"month": start_date.strftime("%b"), "value": month_count})

    # 3. Course performance — scoped to program when selected
    courses_q = db.query(Course).filter(Course.user_id == publisher_id, Course.is_deleted == False)
    if program_id:
        courses_q = courses_q.join(ProgramCourse, ProgramCourse.course_id == Course.id).filter(
            ProgramCourse.program_id == program_id
        )
    my_courses = courses_q.all()

    course_performance = []
    for c in my_courses:
        subs = db.query(func.count(CourseStudent.id)).filter(CourseStudent.course_id == c.id).scalar() or 0
        comp = db.query(func.count(SessionRun.id)).join(DbSession).filter(
            DbSession.course_id == c.id,
            SessionRun.status == SessionRunStatus.COMPLETED
        ).scalar() or 0
        pct = min(100, (comp / max(1, subs * 5)) * 100)
        course_performance.append({
            "name": {"en": c.name or "Untitled", "ar": c.name or "Untitled"},
            "completion": int(pct),
            "subscribers": subs,
        })

    # 4. At Risk Learners — scoped to program when selected
    at_risk = []
    at_risk_q = db.query(User, Course).select_from(CourseStudent).join(User).join(Course).filter(
        Course.user_id == publisher_id, Course.is_deleted == False
    )
    if program_id:
        at_risk_q = at_risk_q.join(ProgramCourse, ProgramCourse.course_id == Course.id).filter(
            ProgramCourse.program_id == program_id
        )
    at_risk_users = at_risk_q.limit(5).all()
    
    for u, c in at_risk_users:
        # Check if they have completions
        has_comp = db.query(func.count(SessionRun.id)).join(DbSession).filter(
            DbSession.course_id == c.id,
            SessionRun.user_id == u.id,
            SessionRun.status == SessionRunStatus.COMPLETED
        ).scalar() or 0
        if has_comp == 0:
            at_risk.append({
                "name": {"en": f"{u.first_name} {u.last_name}", "ar": f"{u.first_name} {u.last_name}"},
                "course": {"en": c.name or "Untitled", "ar": c.name or "Untitled"},
                "progress": 0
            })

    return {
        "publisher_id": publisher_id,
        "total_avatars": total_avatars,
        "total_courses": total_courses,
        "total_subscribers": total_subscribers,
        "total_sessions": total_sessions_run,
        "avatar_stats": [],
        "course_stats": [],
        "total_credits_earned": total_sessions_run * 3.0,  # mock conversion
        "monthly_completions": monthly_completions,
        "course_performance": course_performance,
        "at_risk_learners": at_risk
    }


def get_admin_analytics(db: Session) -> Dict[str, Any]:
    total_users = db.query(func.count(User.id)).scalar() or 0
    total_publishers = db.query(func.count(User.id)).filter(User.role == "publisher").scalar() or 0
    total_subscribers = db.query(func.count(User.id)).filter(User.role == "subscriber").scalar() or 0
    total_avatars = db.query(func.count(Avatar.id)).scalar() or 0
    total_courses = db.query(func.count(Course.id)).filter(Course.is_deleted == False).scalar() or 0
    total_session_runs = db.query(func.count(SessionRun.id)).scalar() or 0

    import datetime
    from dateutil.relativedelta import relativedelta
    today = datetime.date.today()
    monthly_completions = []
    
    for i in range(5, -1, -1):
        month_date = today - relativedelta(months=i)
        start_date = month_date.replace(day=1)
        end_date = (start_date + relativedelta(months=1)) - datetime.timedelta(days=1)
        
        month_count = db.query(func.count(SessionRun.id)).filter(
            SessionRun.status == SessionRunStatus.COMPLETED,
            SessionRun.end_time >= start_date,
            SessionRun.end_time <= end_date
        ).scalar() or 0
        
        monthly_completions.append({
            "month": start_date.strftime("%b"),
            "value": month_count
        })

    # For admin, we can pick top 5 courses across the platform
    top_courses = db.query(Course).filter(Course.is_deleted == False).limit(5).all()
    course_performance = []
    for c in top_courses:
        subs = db.query(func.count(CourseStudent.id)).filter(CourseStudent.course_id == c.id).scalar() or 0
        comp = db.query(func.count(SessionRun.id)).join(DbSession).filter(
            DbSession.course_id == c.id,
            SessionRun.status == SessionRunStatus.COMPLETED
        ).scalar() or 0
        pct = min(100, (comp / max(1, subs * 5)) * 100)
        course_performance.append({
            "name": {"en": c.name or "Untitled", "ar": c.name or "Untitled"},
            "completion": int(pct),
            "subscribers": subs
        })

    return {
        "total_users": total_users,
        "total_publishers": total_publishers,
        "total_subscribers": total_subscribers,
        "total_avatars": total_avatars,
        "total_courses": total_courses,
        "total_session_runs": total_session_runs,
        "active_sessions_today": 0,
        "system_health": 100,
        "total_credits_issued": 0.0,
        "total_credits_consumed": 0.0,
        "sessions_last_7_days": 0,
        "sessions_last_30_days": 0,
        "monthly_completions": monthly_completions,
        "course_performance": course_performance,
        "at_risk_learners": []
    }
