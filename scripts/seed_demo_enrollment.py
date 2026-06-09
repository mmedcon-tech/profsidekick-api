"""
Seed a demo course and enroll all subscribers (for local assistant testing).

Usage (from profsidekick-api root, with DATABASE_URL set):
    python -m scripts.seed_demo_enrollment

Or via Docker:
    docker compose run --rm backend python -m scripts.seed_demo_enrollment
"""

import os
import uuid
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

DEMO_COURSE_ID = "demo-leadership-101"
DEMO_COURSE_NAME = "Basic Level Leadership"
DEMO_SESSION_ID = "demo-session-001"


def seed() -> None:
    from app.database.models import Course, CourseStudent, Session, SessionRun, User
    from app.database.models import SessionRunStatus

    db = SessionLocal()
    try:
        publisher = (
            db.query(User)
            .filter(User.role.in_(["publisher", "professor"]))
            .order_by(User.created_at.asc())
            .first()
        )
        if not publisher:
            print("No publisher found — register a publisher account first.")
            return

        course = db.query(Course).filter(Course.course_id == DEMO_COURSE_ID).first()
        if not course:
            course = Course(
                id=uuid.uuid4(),
                course_id=DEMO_COURSE_ID,
                user_id=publisher.id,
                name=DEMO_COURSE_NAME,
                code="LEAD101",
                description="Introductory leadership programme for demo and testing.",
                department="Training",
                semester="Spring",
                year=2026,
                is_active=True,
                is_deleted=False,
                is_public=True,
            )
            db.add(course)
            db.flush()
            print(f"Created course: {DEMO_COURSE_NAME} ({DEMO_COURSE_ID})")
        else:
            print(f"Course already exists: {DEMO_COURSE_NAME}")

        subscribers = db.query(User).filter(User.role == "subscriber").all()
        enrolled = 0
        for sub in subscribers:
            exists = (
                db.query(CourseStudent)
                .filter(
                    CourseStudent.course_id == course.id,
                    CourseStudent.user_id == sub.id,
                )
                .first()
            )
            if exists:
                continue
            db.add(
                CourseStudent(
                    id=uuid.uuid4(),
                    course_id=course.id,
                    user_id=sub.id,
                    enrollment_date=datetime.utcnow(),
                )
            )
            enrolled += 1
            print(f"  Enrolled subscriber: {sub.username} ({sub.email})")

        session = db.query(Session).filter(Session.session_id == DEMO_SESSION_ID).first()
        if not session:
            session = Session(
                id=uuid.uuid4(),
                session_id=DEMO_SESSION_ID,
                session_number=1,
                user_id=publisher.id,
                course_id=course.id,
                class_name="Leadership Foundations",
                description="Session 1 — introduction to leadership principles.",
                duration=45,
                total_slides=10,
            )
            db.add(session)
            db.flush()
            print(f"Created session: {session.class_name}")

        for sub in subscribers:
            existing_run = (
                db.query(SessionRun)
                .filter(
                    SessionRun.session_id == session.id,
                    SessionRun.user_id == sub.id,
                    SessionRun.status == SessionRunStatus.COMPLETED,
                )
                .first()
            )
            if existing_run:
                continue
            db.add(
                SessionRun(
                    id=uuid.uuid4(),
                    session_run_id=f"run-{sub.username}",
                    session_id=session.id,
                    user_id=sub.id,
                    status=SessionRunStatus.COMPLETED,
                    start_time=datetime.utcnow(),
                    end_time=datetime.utcnow(),
                )
            )
            print(f"  Added completed run for: {sub.username}")

        db.commit()
        print(f"Done. Newly enrolled subscribers: {enrolled}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
