import json
import uuid
from uuid import UUID
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, func, case
from app.database.connection import get_redis
from app.database.models import Session as SessionModel, SessionRun, SessionRunStatus, User, Course, CourseMaterial, SessionMaterial, Avatar, AvatarTemplateRole
from app.schemas.schemas import AssistantParameters, SessionDetails, SessionRunDetails, SessionUpdateDetails, SessionSummary, ClassDetails, PaginationInfo, SessionRunSummary, SessionRunFeedback, SlideData


class SessionService:
    """Service for managing sessions and caching"""

    def __init__(self):
        self.cache_ttl = 3600 * 24  # 24 hours

    @staticmethod
    def _student_slides(slides: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return only student slides, stripping professor solution slides from any API response."""
        return [s for s in (slides or []) if s.get('source') != 'solution']
    
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
        slides_details: List[Dict[str, Any]]
    ) -> str:
        # Validate that the course exists and user has access
        course_id = session_details.get('courseId')
        if not course_id:
            raise ValueError("Course ID is required")
            
        course = db.query(Course).filter(Course.course_id == course_id).first()
        if not course:
            raise ValueError("Course not found")
            
        # Check if user has access to create sessions in this course
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")
            
        if user.role == "publisher" and course.user_id != user_id:
            raise ValueError("You can only create sessions in your own courses")
        elif user.role == "subscriber":
            raise ValueError("Subscribers cannot create sessions")
        
        # Validate and normalise session_mode
        raw_mode = session_details.get('sessionMode') or 'teaching'
        session_mode = raw_mode if raw_mode in ('teaching', 'examination') else 'teaching'

        # Resolve optional avatar + role
        avatar_id = None
        selected_role_id = None
        role_label = None

        raw_avatar_id = session_details.get('avatarId')
        if raw_avatar_id:
            avatar_row = db.query(Avatar).filter(
                Avatar.id == raw_avatar_id,
                Avatar.publisher_id == user_id,
            ).first()
            if avatar_row:
                avatar_id = avatar_row.id

        raw_role_id = session_details.get('selectedRoleId')
        if raw_role_id and avatar_id:
            role_row = db.query(AvatarTemplateRole).filter(
                AvatarTemplateRole.id == raw_role_id,
                AvatarTemplateRole.is_enabled == True,
            ).first()
            if role_row:
                selected_role_id = role_row.id
                role_label = role_row.name

        # Create session in database
        raw_runtime_mode = session_details.get('subscriberRuntimeMode') or 'avatar'
        subscriber_runtime_mode = raw_runtime_mode if raw_runtime_mode in ('avatar', 'chat', 'choice') else 'avatar'

        db_session = SessionModel(
            session_id=session_id,
            user_id=user_id,
            course_id=course.id,  # Use course UUID
            session_number=session_details.get('sessionNumber'),
            session_date=session_details.get('sessionDate'),
            class_name=session_details.get('className'),
            description=session_details.get('description'),
            duration=session_details.get('duration'),
            presentation_details=presentation_details,
            slides_details=slides_details,
            assistant_parameters=session_details.get('assistantParameters'),
            session_mode=session_mode,
            subscriber_runtime_mode=subscriber_runtime_mode,
            avatar_id=avatar_id,
            selected_role_id=selected_role_id,
            role_label=role_label,
        )
        
        db.add(db_session)
        db.flush()  # Get the session ID so we can link materials

        # Link any selected course materials to this session
        material_ids = session_details.get('materialId') or []
        for mat_id in material_ids:
            if not mat_id:
                continue
            course_material = db.query(CourseMaterial).filter(
                CourseMaterial.id == mat_id
            ).first()
            if course_material:
                session_material = SessionMaterial(
                    session_id=db_session.id,
                    course_material_id=course_material.id,
                    is_included=True,
                )
                db.add(session_material)

        db.commit()

        return session_id
    
    async def get_session(self, db: Session, session_id: str) -> Optional[SessionDetails]:
        db_session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        if not db_session:
            return None

        user = db_session.user
        course = db_session.course
        if not user:
            raise ValueError(f"Session '{session_id}' references a user that no longer exists")
        if not course:
            raise ValueError(f"Session '{session_id}' references a course that no longer exists")

        slides = self._student_slides(db_session.slides_details)
        # Backfill id for slides stored before the id field was added
        for i, slide in enumerate(slides):
            if slide.get('id') is None:
                slide['id'] = slide.get('slideNumber', i + 1)

        session_data = {
            'sessionId': str(db_session.session_id),
            'userId': str(user.id),
            'username': user.username,
            'courseId': course.course_id,
            'courseName': course.name,
            'className': db_session.class_name,
            'courseCode': course.code,
            'sessionNumber': db_session.session_number,
            'sessionDate': db_session.session_date,
            'description': db_session.description,
            'duration': db_session.duration,
            'presentationDetails': db_session.presentation_details,
            'slidesDetails': slides,
            'assistantParameters': db_session.assistant_parameters,
            'sessionMode': getattr(db_session, 'session_mode', 'teaching') or 'teaching',
            'subscriberRuntimeMode': getattr(db_session, 'subscriber_runtime_mode', 'avatar') or 'avatar',
        }

        return SessionDetails(**session_data)

    async def get_user(self, db: Session, username: str, password: str) -> Optional[User]:
        db_user = db.query(User).filter(User.username == username, User.password == password).first()
        print(f"🔍 User found: {db_user}")
        if not db_user:
            return None
        return db_user
    
    async def get_user_by_id(self, db: Session, user_id: str) -> Optional[User]:
        db_user = db.query(User).filter(User.id == user_id).first()
        if not db_user:
            return None
        return db_user
    
    async def update_session(self, db: Session, session_id: str, session_details: SessionUpdateDetails) -> Optional[SessionDetails]:
        db_session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        if not db_session:
            return None

        user = db_session.user
        course = db_session.course
        if not user:
            raise ValueError(f"Session '{session_id}' references a user that no longer exists")
        if not course:
            raise ValueError(f"Session '{session_id}' references a course that no longer exists")

        db_session.assistant_parameters = session_details.assistantParameters.model_dump()
        db.commit()
        return SessionDetails(
            sessionId=str(db_session.session_id),
            courseId=course.course_id,
            courseName=course.name,
            className=db_session.class_name,
            courseCode=course.code,
            sessionNumber=db_session.session_number,
            sessionDate=db_session.session_date,
            description=db_session.description,
            duration=db_session.duration,
            presentationDetails=db_session.presentation_details,
            slidesDetails=self._student_slides(db_session.slides_details),
            assistantParameters=db_session.assistant_parameters,
            userId=str(user.id),
            username=user.username
        )

    async def update_session_slides(self, db: Session, session_id: str, slides_details: List[Dict[str, Any]]) -> Optional[SessionDetails]:
        db_session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        if not db_session:
            return None

        user = db_session.user
        course = db_session.course
        if not user:
            raise ValueError(f"Session '{session_id}' references a user that no longer exists")
        if not course:
            raise ValueError(f"Session '{session_id}' references a course that no longer exists")

        db_session.slides_details = slides_details
        db.commit()
        return SessionDetails(
            sessionId=str(db_session.session_id),
            courseId=course.course_id,
            courseName=course.name,
            className=db_session.class_name,
            courseCode=course.code,
            sessionNumber=db_session.session_number,
            sessionDate=db_session.session_date,
            description=db_session.description,
            duration=db_session.duration,
            presentationDetails=db_session.presentation_details,
            slidesDetails=self._student_slides(db_session.slides_details),
            assistantParameters=db_session.assistant_parameters,
            userId=str(user.id),
            username=user.username
        )
    


    async def delete_session(self, db: Session, session_id: str) -> bool:
        db_session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
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
        runtime_mode_used: Optional[str] = None,
    ) -> SessionRun:
        db_session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        if not db_session:
            return False

        session_run_id = self.generate_session_run_id()

        session_run = SessionRun(
            session_run_id=session_run_id,
            session_id=db_session.session_id,
            user_id=user_id,
            session_run_metadata={},
            assistant_parameters=assistant_parameters.model_dump(),
            status=SessionRunStatus.ACTIVE,
            end_time=None,
            runtime_mode_used=runtime_mode_used,
        )

        db_session.session_runs.append(session_run)

        db.commit()
        return session_run
    
    async def get_session_run(self, db: Session, session_id: str, session_run_id: str) -> Optional[SessionRun]:
        """
        Return the SessionRun identified by both session_id AND session_run_id.

        Enforces the API contract: a run is only returned when it actually
        belongs to the stated session.  Filtering on session_run_id alone would
        allow any caller who knows a run ID to access it regardless of which
        session it belongs to.
        """
        parent = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        if not parent:
            return None

        # SessionRun.session_id is the UUID FK to sessions.id (the UUID PK).
        # parent.session_id is the human-readable string slug — do NOT use it here.
        run = db.query(SessionRun).filter(
            SessionRun.session_id == parent.id,
            SessionRun.session_run_id == session_run_id,
        ).first()
        return run
    
    async def stop_session_run(self, db: Session, session_id: str, session_run_id: str, session_run_metadata: Optional[dict] = None) -> Optional[SessionRun]:
        # First get the session by string session_id to get the UUID
        db_session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        if not db_session:
            return None
            
        # Then query SessionRun using the UUID
        session_run = db.query(SessionRun).filter(
            SessionRun.session_id == db_session.id, 
            SessionRun.session_run_id == session_run_id
        ).first()
        
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
        avatar_id: Optional[str] = None,
    ) -> Tuple[List[SessionSummary], PaginationInfo]:
        """
        Get paginated sessions for a user with filtering and sorting.
        Optionally filter by avatar_id to scope results to a specific avatar.
        """
        # Base query for sessions belonging to the user
        base_query = db.query(SessionModel).filter(SessionModel.user_id == user_id)

        # Filter by avatar if requested
        if avatar_id:
            base_query = base_query.filter(SessionModel.avatar_id == avatar_id)
        
        # Apply status filter if provided
        if status:
            if status == "active":
                # Sessions that have at least one active run
                base_query = base_query.join(SessionRun).filter(SessionRun.status == SessionRunStatus.ACTIVE).distinct()
            elif status == "completed":
                # Sessions that have runs but no active runs
                subquery_active = db.query(SessionRun.session_id).filter(SessionRun.status == SessionRunStatus.ACTIVE).subquery()
                subquery_has_runs = db.query(SessionRun.session_id).subquery()
                base_query = base_query.join(subquery_has_runs, SessionModel.id == subquery_has_runs.c.session_id).filter(
                    ~SessionModel.id.in_(db.query(subquery_active.c.session_id))
                ).distinct()
            elif status == "draft":
                # Sessions with no runs
                subquery = db.query(SessionRun.session_id).subquery()
                base_query = base_query.filter(~SessionModel.id.in_(db.query(subquery.c.session_id)))
        
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
            # Count only student slides (solution slides are AI-only, not rendered)
            total_slides = len(self._student_slides(session.slides_details))
            
            # Get run statistics
            runs = db.query(SessionRun).filter(SessionRun.session_id == session.id).all()
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
                last_accessed_at = last_run.created_at  # Use last run as last access for now
            
            # Create ClassDetails
            class_details = ClassDetails(
                className=session.class_name or "",
                courseName=session.course.name or "",
                courseCode=session.course.code or "",
                courseId=session.course.course_id or "",  # slug used in URLs
                description=session.description,
                duration=session.duration or 0
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
                sessionMode=getattr(session, 'session_mode', 'teaching') or 'teaching',
                avatarId=str(session.avatar_id) if session.avatar_id else None,
                selectedRoleId=str(session.selected_role_id) if session.selected_role_id else None,
                roleLabel=session.role_label,
            )
            
            session_summaries.append(session_summary)
        
        # Calculate total pages
        total_pages = (total + limit - 1) // limit if total > 0 else 1
        
        # Create pagination info
        pagination = PaginationInfo(
            page=page,
            limit=limit,
            total=total,
            totalPages=total_pages
        )
        
        return session_summaries, pagination
    
    async def get_session_runs(self, db: Session, session_id: str, user_id: str) -> Tuple[List[SessionRunSummary], int]:
        """
        Get all runs for a specific session
        """
        # First verify the session exists and belongs to the user
        db_session = db.query(SessionModel).filter(
            SessionModel.session_id == session_id,
            SessionModel.user_id == user_id
        ).first()
        
        if not db_session:
            return [], 0
        
        # Get all runs for this session
        runs = db.query(SessionRun).filter(SessionRun.session_id == db_session.id).order_by(desc(SessionRun.created_at)).all()
        
        # Count only student slides (solution slides are AI-only, not rendered)
        total_slides = len(self._student_slides(db_session.slides_details))
        
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
                feedback_data = run.session_run_metadata.get('feedback')
                if feedback_data:
                    feedback = SessionRunFeedback(
                        rating=feedback_data.get('rating'),
                        general_feedback=feedback_data.get('general_feedback'),
                        issues_encountered=feedback_data.get('issues_encountered'),
                        suggestions=feedback_data.get('suggestions')
                    )
                
                slides_completed = run.session_run_metadata.get('slides_completed')
            
            # Resolve avatar name from parent session
            avatar_name = None
            avatar_id_str = None
            try:
                if db_session.avatar and db_session.avatar.name:
                    avatar_name = db_session.avatar.name
                    avatar_id_str = str(db_session.avatar.id)
            except Exception:
                pass

            run_summary = SessionRunSummary(
                sessionRunId=run.session_run_id,
                sessionId=session_id,
                status=run.status.value if hasattr(run.status, 'value') else str(run.status),
                startedAt=run.start_time,
                endedAt=run.end_time,
                duration=duration,
                feedback=feedback,
                slidesCompleted=slides_completed,
                totalSlides=total_slides,
                avatarId=avatar_id_str,
                avatarName=avatar_name,
                roleAtStart=run.role_at_start,
                sessionMode="realtime",
                className=db_session.class_name,
            )
            
            run_summaries.append(run_summary)
        
        return run_summaries, len(run_summaries)