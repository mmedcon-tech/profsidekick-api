import json
import uuid
from uuid import UUID
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, func, case
from app.database.connection import get_redis
from app.database.models import (
    Session as SessionModel,
    SessionRun,
    SessionRunStatus,
    User,
    Course,
)
from app.schemas.schemas import (
    AssistantParameters,
    SessionDetails,
    SessionRunDetails,
    SessionUpdateDetails,
    SessionSummary,
    ClassDetails,
    PaginationInfo,
    SessionRunSummary,
    SessionRunFeedback,
    SlideData,
)


class SessionService:
    """Service for managing sessions and caching"""

    def __init__(self):
        self.cache_ttl = 3600 * 24  # 24 hours

    def generate_session_id(self) -> str:
        """Generate a unique session ID"""
        return f"sess_{uuid.uuid4().hex[:12]}"

    def generate_session_run_id(self) -> str:
        """Generate a unique session run ID"""
        return f"run_{uuid.uuid4().hex[:12]}"

    async def create_session(
        self,
        db: Session,
        user_id: UUID,
        session_id: str,
        presentation_details: Dict[str, Any],
        session_details: Dict[str, Any],
        slides_details: List[Dict[str, Any]],
    ) -> str:
        # Validate that the course exists and user has access
        course_id = session_details.get("courseId")
        if not course_id:
            raise ValueError("Course ID is required")

        course = db.query(Course).filter(Course.course_id == course_id).first()
        if not course:
            raise ValueError("Course not found")

        # Check if user has access to create sessions in this course
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")

        if user.role == "professor" and course.user_id != user_id:
            raise ValueError("You can only create sessions in your own courses")
        elif user.role == "student":
            raise ValueError("Students cannot create sessions")

        # Create session in database
        db_session = SessionModel(
            session_id=session_id,
            user_id=user_id,
            course_id=course.id,  # Use course UUID
            session_number=session_details.get("sessionNumber"),
            session_date=session_details.get("sessionDate"),
            class_name=session_details.get("className"),
            description=session_details.get("description"),
            duration=session_details.get("duration"),
            presentation_details=presentation_details,
            slides_details=slides_details,
            assistant_parameters=session_details.get("assistantParameters"),
        )

        db.add(db_session)
        db.flush()  # Get the session ID

        db.commit()

        return session_id

    async def get_session(
        self, db: Session, session_id: str
    ) -> Optional[SessionDetails]:
        db_session = (
            db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        )
        if not db_session:
            return None
        print("Session found")
        session_data = {
            "sessionId": str(db_session.session_id),
            "userId": str(db_session.user.id),
            "username": db_session.user.username,
            "courseId": db_session.course.course_id,
            "courseName": db_session.course.name,
            "className": db_session.class_name,
            "courseCode": db_session.course.code,
            "sessionNumber": db_session.session_number,
            "sessionDate": db_session.session_date,
            "description": db_session.description,
            "duration": db_session.duration,
            "presentationDetails": db_session.presentation_details,
            "slidesDetails": db_session.slides_details,
            "assistantParameters": db_session.assistant_parameters,
        }

        return SessionDetails(**session_data)

    async def get_user(
        self, db: Session, username: str, password: str
    ) -> Optional[User]:
        db_user = (
            db.query(User)
            .filter(User.username == username, User.password == password)
            .first()
        )
        print(f"🔍 User found: {db_user}")
        if not db_user:
            return None
        return db_user

    async def get_user_by_id(self, db: Session, user_id: str) -> Optional[User]:
        db_user = db.query(User).filter(User.id == user_id).first()
        if not db_user:
            return None
        return db_user

    async def update_session(
        self, db: Session, session_id: str, session_details: SessionUpdateDetails
    ) -> Optional[SessionDetails]:
        db_session = (
            db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        )
        if not db_session:
            return None
        # db_session.course_name = session_details.courseName
        # db_session.class_name = session_details.className
        # db_session.course_code = session_details.courseCode
        # db_session.description = session_details.description
        # db_session.duration = session_details.duration
        db_session.assistant_parameters = (
            session_details.assistantParameters.model_dump()
        )
        db.commit()
        print("Session updated")
        return SessionDetails(
            sessionId=str(db_session.session_id),
            courseId=db_session.course.course_id,
            courseName=db_session.course.name,
            className=db_session.class_name,
            courseCode=db_session.course.code,
            sessionNumber=db_session.session_number,
            sessionDate=db_session.session_date,
            description=db_session.description,
            duration=db_session.duration,
            presentationDetails=db_session.presentation_details,
            slidesDetails=db_session.slides_details,
            assistantParameters=db_session.assistant_parameters,
            userId=str(db_session.user.id),
            username=db_session.user.username,
        )

    async def update_session_slides(
        self, db: Session, session_id: str, slides_details: List[Dict[str, Any]]
    ) -> Optional[SessionDetails]:
        db_session = (
            db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        )
        if not db_session:
            return None
        db_session.slides_details = slides_details
        db.commit()
        print("Session slides updated")
        return SessionDetails(
            sessionId=str(db_session.session_id),
            courseId=db_session.course.course_id,
            courseName=db_session.course.name,
            className=db_session.class_name,
            courseCode=db_session.course.code,
            sessionNumber=db_session.session_number,
            sessionDate=db_session.session_date,
            description=db_session.description,
            duration=db_session.duration,
            presentationDetails=db_session.presentation_details,
            slidesDetails=db_session.slides_details,
            assistantParameters=db_session.assistant_parameters,
            userId=str(db_session.user.id),
            username=db_session.user.username,
        )

    async def delete_session(self, db: Session, session_id: str) -> bool:
        db_session = (
            db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        )
        if not db_session:
            return False

        db.delete(db_session)
        db.commit()
        return True

    async def start_session_run(
        self,
        db: Session,
        session_id: str,
        user_id: str,
        assistant_parameters: AssistantParameters,
    ) -> SessionRun:
        print("Starting session run")
        db_session = (
            db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        )
        if not db_session:
            return False
        print("Session ")
        session_run_id = self.generate_session_run_id()

        session_run = SessionRun(
            session_run_id=session_run_id,
            session_id=db_session.session_id,
            user_id=user_id,
            session_run_metadata={},
            assistant_parameters=assistant_parameters.model_dump(),  # Convert Pydantic object to dict
            status=SessionRunStatus.ACTIVE,
            end_time=None,
        )

        db_session.session_runs.append(session_run)

        db.commit()
        return session_run

    async def get_session_run(
        self, db: Session, session_id: str, session_run_id: str
    ) -> Optional[SessionRun]:
        """
        Get a session run
        """
        # First get the session by string session_id to get the UUID
        db_session = (
            db.query(SessionRun)
            .filter(SessionRun.session_run_id == session_run_id)
            .first()
        )
        if not db_session:
            return None

        return db_session

    async def stop_session_run(
        self,
        db: Session,
        session_id: str,
        session_run_id: str,
        session_run_metadata: Optional[dict] = None,
    ) -> Optional[SessionRun]:
        # First get the session by string session_id to get the UUID
        db_session = (
            db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        )
        if not db_session:
            return None

        # Then query SessionRun using the UUID
        session_run = (
            db.query(SessionRun)
            .filter(
                SessionRun.session_id == db_session.id,
                SessionRun.session_run_id == session_run_id,
            )
            .first()
        )

        if not session_run:
            return None

        session_run.status = SessionRunStatus.COMPLETED
        session_run.end_time = datetime.now()
        session_run.session_run_metadata = session_run_metadata
        db.commit()
        return session_run

    async def get_sessions_paginated(
        self,
        db: Session,
        user_id: str,
        page: int = 1,
        limit: int = 20,
        status: Optional[str] = None,
        sort: str = "created_desc",
    ) -> Tuple[List[SessionSummary], PaginationInfo]:
        """
        Get paginated sessions for a user with filtering and sorting
        """
        # Base query for sessions belonging to the user
        base_query = db.query(SessionModel).filter(SessionModel.user_id == user_id)

        # Apply status filter if provided
        if status:
            if status == "active":
                # Sessions that have at least one active run
                base_query = (
                    base_query.join(SessionRun)
                    .filter(SessionRun.status == SessionRunStatus.ACTIVE)
                    .distinct()
                )
            elif status == "completed":
                # Sessions that have runs but no active runs
                subquery_active = (
                    db.query(SessionRun.session_id)
                    .filter(SessionRun.status == SessionRunStatus.ACTIVE)
                    .subquery()
                )
                subquery_has_runs = db.query(SessionRun.session_id).subquery()
                base_query = (
                    base_query.join(
                        subquery_has_runs,
                        SessionModel.id == subquery_has_runs.c.session_id,
                    )
                    .filter(
                        ~SessionModel.id.in_(db.query(subquery_active.c.session_id))
                    )
                    .distinct()
                )
            elif status == "draft":
                # Sessions with no runs
                subquery = db.query(SessionRun.session_id).subquery()
                base_query = base_query.filter(
                    ~SessionModel.id.in_(db.query(subquery.c.session_id))
                )

        # Apply sorting
        if sort == "created_desc":
            base_query = base_query.order_by(desc(SessionModel.created_at))
        elif sort == "created_asc":
            base_query = base_query.order_by(asc(SessionModel.created_at))
        elif sort == "updated_desc":
            base_query = base_query.order_by(desc(SessionModel.updated_at))
        elif sort == "updated_asc":
            base_query = base_query.order_by(asc(SessionModel.updated_at))
        else:
            # Default to created_desc
            base_query = base_query.order_by(desc(SessionModel.created_at))

        # Get total count for pagination (before applying limit/offset)
        total = base_query.count()

        # Apply pagination
        offset = (page - 1) * limit
        sessions = base_query.offset(offset).limit(limit).all()

        # Convert to SessionSummary objects
        session_summaries = []
        for session in sessions:
            # Count total slides
            total_slides = 0
            if session.slides_details and isinstance(session.slides_details, list):
                total_slides = len(session.slides_details)

            # Get run statistics
            runs = (
                db.query(SessionRun).filter(SessionRun.session_id == session.id).all()
            )
            run_count = len(runs)

            # Determine session status based on runs
            session_status = "draft"  # Default
            if runs:
                active_runs = [r for r in runs if r.status == SessionRunStatus.ACTIVE]
                if active_runs:
                    session_status = "active"
                else:
                    session_status = "completed"

            # Get last run time and last accessed time
            last_run_at = None
            last_accessed_at = None
            if runs:
                last_run = max(runs, key=lambda r: r.created_at)
                last_run_at = last_run.created_at
                last_accessed_at = (
                    last_run.created_at
                )  # Use last run as last access for now

            # Create ClassDetails
            class_details = ClassDetails(
                className=session.class_name or "",
                courseName=session.course.name or "",
                courseCode=session.course.code or "",
                description=session.description,
                duration=session.duration or 0,
            )

            # Create SessionSummary
            session_summary = SessionSummary(
                sessionId=session.session_id,
                classDetails=class_details,
                status=session_status,
                totalSlides=total_slides,
                createdAt=session.created_at,
                updatedAt=session.updated_at,
                lastAccessedAt=last_accessed_at,
                runCount=run_count,
                lastRunAt=last_run_at,
            )

            session_summaries.append(session_summary)

        # Calculate total pages
        total_pages = (total + limit - 1) // limit if total > 0 else 1

        # Create pagination info
        pagination = PaginationInfo(
            page=page, limit=limit, total=total, totalPages=total_pages
        )

        return session_summaries, pagination

    async def get_session_runs(
        self, db: Session, session_id: str, user_id: str
    ) -> Tuple[List[SessionRunSummary], int]:
        """
        Get all runs for a specific session
        """
        # First verify the session exists and belongs to the user
        db_session = (
            db.query(SessionModel)
            .filter(
                SessionModel.session_id == session_id, SessionModel.user_id == user_id
            )
            .first()
        )

        if not db_session:
            return [], 0

        # Get all runs for this session
        runs = (
            db.query(SessionRun)
            .filter(SessionRun.session_id == db_session.id)
            .order_by(desc(SessionRun.created_at))
            .all()
        )

        # Count total slides in the session
        total_slides = 0
        if db_session.slides_details and isinstance(db_session.slides_details, list):
            total_slides = len(db_session.slides_details)

        run_summaries = []
        for run in runs:
            # Calculate duration if both start and end times exist
            duration = None
            if run.start_time and run.end_time:
                duration = int((run.end_time - run.start_time).total_seconds() / 60)

            # Extract feedback from session_run_metadata if it exists
            feedback = None
            slides_completed = None

            if run.session_run_metadata and isinstance(run.session_run_metadata, dict):
                feedback_data = run.session_run_metadata.get("feedback")
                if feedback_data:
                    feedback = SessionRunFeedback(
                        rating=feedback_data.get("rating"),
                        general_feedback=feedback_data.get("general_feedback"),
                        issues_encountered=feedback_data.get("issues_encountered"),
                        suggestions=feedback_data.get("suggestions"),
                    )

                slides_completed = run.session_run_metadata.get("slides_completed")

            run_summary = SessionRunSummary(
                sessionRunId=run.session_run_id,
                sessionId=session_id,
                status=(
                    run.status.value
                    if hasattr(run.status, "value")
                    else str(run.status)
                ),
                startedAt=run.start_time,
                endedAt=run.end_time,
                duration=duration,
                feedback=feedback,
                slidesCompleted=slides_completed,
                totalSlides=total_slides,
            )

            run_summaries.append(run_summary)

        return run_summaries, len(run_summaries)
