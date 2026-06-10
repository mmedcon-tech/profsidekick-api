import logging
from PIL import Image
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import requests
import httpx
from io import BytesIO
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import (
    Session, SessionRun, SessionRunStatus, User,
    Avatar, AvatarSubscription, AvatarTemplate, AvatarTemplateVersion, AvatarTemplateRole,
    Course, CourseStudent,
)
from app.services.summarization_service import (
    generate_run_summary, get_recent_session_summary, get_user_memories,
)
from app.schemas.schemas import SessionDetails, SlideData, PresentationData, AssistantParameters, SessionRunDetails, EphemeralTokenResponse, SessionUpdateDetails, SessionsListResponse, SessionRunsListResponse, SessionCreateRequest
from app.services.file_processor import FileProcessor
from app.services.openai_service import OpenAIService
from app.services.session_service import SessionService
from app.services.rag_service import ingest_session_document_background, retrieve_context
from pydantic import BaseModel
class SearchRequest(BaseModel):
    query: str
    course_id: Optional[str] = None
from app.dependencies.auth import get_current_user, get_optional_user
from app.config import settings

# Set up logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/api", tags=["sessions"])

# Initialize services
file_processor = FileProcessor()
openai_service = OpenAIService()
session_service = SessionService()


async def _process_upload(
    fp: FileProcessor,
    ais: OpenAIService,
    file_path: str,
    filename: str,
    session_id: str,
    *,
    source: str,
    vision_instructions: Optional[str],
    vision_model: Optional[str],
):
    """
    Unified slide-extraction entry point.

    All formats → convert to images → Vision API:
      PDF               : pdf2image directly
      PPTX / PPT / DOCX : LibreOffice → PDF → pdf2image

    Returns a list of slide dicts:
      { slideNumber, title, content, imagePath, thumbnailPath, source }
    """
    if fp.is_text_extraction_format(filename):
        logger.info(f"⚙️ Extracting text content from {Path(filename).suffix.upper()} file")
        slides = fp.extract_text_content(file_path, source=source)
        logger.info(f"✅ Extracted {len(slides)} sections from {filename}")
        return slides

    # All other formats → LibreOffice (for DOCX/PPTX) or direct (for PDF) → images → Vision API
    logger.info(f"⚙️ Converting {filename} to images for Vision processing")
    ext = Path(filename).suffix.lower()
    try:
        slide_images, images_paths = await fp.convert_presentation_to_images(file_path, session_id)
    except Exception as exc:
        # Any failure in the image-conversion pipeline (LibreOffice not installed,
        # conversion error, poppler/pdf2image error) → fall back to text extraction
        # for DOCX and PPTX so session creation still succeeds with slide text.
        # .ppt (legacy binary OLE format) and .pdf cannot be text-extracted — re-raise.
        if ext in (".docx", ".pptx"):
            logger.warning(
                "⚠️ Image conversion failed (%s: %s) — falling back to text extraction "
                "for %s. Fix the pipeline to enable Vision AI slide analysis.",
                type(exc).__name__, exc, filename,
            )
            slides = fp.extract_text_content(file_path, source=source)
            slides = fp.render_slides_as_images(slides, session_id)
            logger.info("✅ Rendered %d slide image(s) from text content", len(slides))
            return slides
        raise
    logger.info(f"✅ Converted {len(slide_images)} slides to images")
    slides = await ais.process_slides_with_vision(
        slide_images, images_paths, session_id, vision_instructions, vision_model
    )
    for s in slides:
        s["source"] = source
    return slides


@router.post("/sessions/create", response_model=SessionDetails)
async def create_session(
    background_tasks: BackgroundTasks,
    presentation: UploadFile = File(...),
    solution_file: Optional[UploadFile] = File(None),
    sessionDetails: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new session.
    presentation   — student PDF (rendered in the teaching UI).
    solution_file  — optional professor solution PDF (processed for AI context only, never rendered).
    """
    try:
        # Parse session details
        logger.info(f"📋 Parsing session details: {sessionDetails}")
        session_details_dict = json.loads(sessionDetails)

        # Validate that courseId is present
        if 'courseId' not in session_details_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="courseId is required in session details"
            )

        # ── Subscriber session-creation gate (fail fast, before any file I/O) ──
        if current_user.role == "subscriber":
            course_id_str = session_details_dict['courseId']
            gate_course = db.query(Course).filter(Course.course_id == course_id_str).first()
            if not gate_course:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Course not found.",
                )
            if not gate_course.allow_subscriber_sessions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This course does not allow subscribers to create sessions.",
                )
            gate_enrollment = db.query(CourseStudent).filter(
                CourseStudent.course_id == gate_course.id,
                CourseStudent.user_id == current_user.id,
            ).first()
            if not gate_enrollment:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You must be enrolled in this course to create a session.",
                )

        # Read student file content
        logger.info(f"📂 Reading file content: {presentation.filename}")
        file_content = await presentation.read()
        logger.info(f"✅ File read successfully, size: {len(file_content)} bytes")

        # Enforce size cap before any processing
        if len(file_content) > settings.max_file_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum allowed size is {settings.max_file_size // (1024 * 1024)} MB. Your file is {len(file_content) / (1024 * 1024):.1f} MB."
            )

        # Validate student file
        logger.info(f"🔍 Validating file: {presentation.filename}")
        is_valid, error_message = file_processor.validate_file(file_content, presentation.filename)
        if not is_valid:
            logger.error(f"❌ File validation failed: {error_message}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File validation failed: {error_message}"
            )

        # Generate session ID
        logger.info(f"🆔 Generating session ID")
        session_id = session_service.generate_session_id()
        logger.info(f"✅ Session ID generated: {session_id}")

        # Save student file
        file_path = await file_processor.save_uploaded_file(file_content, presentation.filename, session_id)
        logger.info(f"✅ File saved to: {file_path}")

        presentation_details_dict = {
            "filename": presentation.filename,
            "filePath": file_path,
            "fileSize": len(file_content),
            "fileType": Path(presentation.filename).suffix.lower(),
        }

        # ── Process student file: PDF → Vision pipeline; PPTX/DOCX → text extraction ──
        student_slides = await _process_upload(
            file_processor, openai_service,
            file_path, presentation.filename, session_id,
            source="student",
            vision_instructions=session_details_dict.get('visionInstructions'),
            vision_model=session_details_dict.get('visionModel'),
        )
        logger.info(f"✅ Student slides processed ({len(student_slides)} slides)")

        # Process professor solution file if provided
        solution_slides = []
        if solution_file and solution_file.filename:
            logger.info(f"📂 Reading solution file: {solution_file.filename}")
            sol_content = await solution_file.read()
            if len(sol_content) > settings.max_file_size:
                raise HTTPException(
                    status_code=413,
                    detail=f"Solution file too large. Maximum allowed size is {settings.max_file_size // (1024 * 1024)} MB. Your file is {len(sol_content) / (1024 * 1024):.1f} MB."
                )
            sol_valid, sol_error = file_processor.validate_file(sol_content, solution_file.filename)
            if not sol_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Solution file validation failed: {sol_error}"
                )
            sol_path = await file_processor.save_uploaded_file(sol_content, solution_file.filename, session_id)
            solution_slides = await _process_upload(
                file_processor, openai_service,
                sol_path, solution_file.filename, session_id,
                source="solution",
                vision_instructions=session_details_dict.get('visionInstructions'),
                vision_model=session_details_dict.get('visionModel'),
            )
            logger.info(f"✅ Solution slides processed ({len(solution_slides)} slides)")

        slides_details = student_slides + solution_slides

        # Create session with slides
        logger.info(f"📚 Creating session with slides")
        session_id = await session_service.create_session(
            db,
            current_user.id,
            session_id,
            presentation_details_dict,
            session_details_dict,
            slides_details,
        )
        logger.info(f"✅ Session created with ID: {session_id}")

        db_session_raw = db.query(Session).filter(Session.session_id == session_id).first()
        if db_session_raw:
            background_tasks.add_task(
                ingest_session_document_background,
                db_session_raw.id,
                slides_details,
            )

        # Format slides for response
        logger.info(f"📋 Formatting slides for response")
        response_slides = []
        for slide_details in slides_details:
            response_slides.append(SlideData(
                id=slide_details.get('slideNumber'),
                slideNumber=slide_details.get('slideNumber'),
                title=slide_details.get('title'),
                imagePath=slide_details.get('imagePath', ''),
                thumbnailPath=slide_details.get('thumbnailPath', ''),
                content=slide_details.get('content'),
                visionInstructions=slide_details.get('visionInstructions', ''),
                visionModel=slide_details.get('visionModel', ''),
            ))

        presentation_details = PresentationData(
            filename=presentation_details_dict.get('filename'),
            filePath=presentation_details_dict.get('filePath'),
            fileSize=presentation_details_dict.get('fileSize'),
            fileType=presentation_details_dict.get('fileType'),
        )
        
        # Get the created session from database to return complete information
        created_session = await session_service.get_session(db, session_id)
        if not created_session:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve created session"
            )
        
        logger.info(f"🎉 Returning successful response with {len(response_slides)} slides")
        return created_session
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating session: {e}"
        )

@router.get("/sessions/{session_id}", response_model=SessionDetails)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """
    Get a session by ID.

    Authentication is optional to support the shared-link (guest) flow where
    students follow a teacher-provided URL without a platform account.
    The session_id itself acts as the access credential in that scenario.

    Authenticated callers receive the same response; the identity is available
    here for future per-user filtering or audit logging.
    """
    try:
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )
        return session
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Error getting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting session: {e}",
        )


@router.post("/sessions/{session_id}/update", response_model=SessionDetails)
async def update_session(
    session_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update assistant_parameters for a session.
    Only the session owner or an admin may call this.
    """
    try:
        if not request_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request data is required",
            )

        # Ownership check before touching any data.
        db_session = db.query(Session).filter(Session.session_id == session_id).first()
        if not db_session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        if current_user.role != "admin" and str(db_session.user_id) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only modify your own sessions",
            )

        session_details = SessionUpdateDetails(**request_data)
        session = await session_service.update_session(db, session_id, session_details)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        return session
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"❌ Invalid request data: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid request data: {str(e)}",
        )
    except Exception as e:
        logger.error(f"❌ Error updating session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating session: {e}",
        )

@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Hard-delete a session and all its runs.
    Only the session owner or an admin may call this.
    This operation is irreversible.
    """
    try:
        # Ownership check before the irreversible delete.
        db_session = db.query(Session).filter(Session.session_id == session_id).first()
        if not db_session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        if current_user.role != "admin" and str(db_session.user_id) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own sessions",
            )

        deleted = await session_service.delete_session(db, session_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )
        return {"message": "Session deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting session: {e}",
        )

@router.patch("/sessions/{session_id}/role")
async def update_session_role(
    session_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update the selected role on a session.
    Validates the role exists, is enabled, and belongs to the session's avatar's template.
    """
    try:
        db_session = db.query(Session).filter(Session.session_id == session_id).first()
        if not db_session:
            raise HTTPException(status_code=404, detail="Session not found")
        if str(db_session.user_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="Not authorised")

        role_id = request_data.get("role_id")
        if not role_id:
            raise HTTPException(status_code=400, detail="role_id is required")

        role_row = db.query(AvatarTemplateRole).filter(
            AvatarTemplateRole.id == role_id,
            AvatarTemplateRole.is_enabled == True,
        ).first()
        if not role_row:
            raise HTTPException(status_code=404, detail="Role not found or disabled")

        db_session.selected_role_id = role_row.id
        db_session.role_label = role_row.name
        db.commit()

        return {"sessionId": session_id, "roleId": str(role_row.id), "roleLabel": role_row.name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating session role: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/run/start", response_model=SessionRunDetails)
async def start_session_run(
    session_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start a session run.

    assistant_parameters is optional in the request body.  When absent the
    session's stored assistant_parameters are used as-is — this allows
    subscriber callers to launch with an empty body ({}).
    """
    try:
        # Load the session first so we can fall back to its stored params.
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        assistant_parameters_dict = request_data.get("assistant_parameters")

        if not assistant_parameters_dict:
            # Fall back to the params already stored on the session.
            stored = session.assistantParameters
            if stored is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Session has no assistant_parameters and none were supplied in the request",
                )
            # session.assistantParameters is an AssistantParameters Pydantic model
            # (SessionDetails coerces the JSONB dict into it).  The ** operator
            # requires a mapping with .keys(); Pydantic models don't expose that.
            # model_dump() produces the plain dict that AssistantParameters() needs.
            assistant_parameters_dict = stored.model_dump()

        assistant_parameters = AssistantParameters(**assistant_parameters_dict)

        # ── Subscriber session gate ────────────────────────────────────────────
        db_session_raw = db.query(Session).filter(Session.session_id == session_id).first()
        if current_user.role == "subscriber":
            if not db_session_raw:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")

            # Gate 1: course must exist and allow subscriber sessions
            course = db.query(Course).filter(Course.id == db_session_raw.course_id).first()
            if not course:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Session has no associated course.",
                )
            if not course.allow_subscriber_sessions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This course does not allow subscriber sessions.",
                )

            # Gate 2: subscriber must be enrolled
            enrolled = db.query(CourseStudent).filter_by(
                course_id=db_session_raw.course_id,
                user_id=current_user.id,
            ).first()
            if not enrolled:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You must be enrolled in this course to start a session.",
                )

            # Gate 3: avatar subscription — only enforced when the session has an avatar
            if db_session_raw.avatar_id:
                from datetime import datetime as _dt
                sub = db.query(AvatarSubscription).filter(
                    AvatarSubscription.subscriber_id == current_user.id,
                    AvatarSubscription.avatar_id == db_session_raw.avatar_id,
                    AvatarSubscription.is_active.is_(True),
                ).first()
                if sub and sub.expires_at and sub.expires_at < _dt.utcnow():
                    sub.is_active = False
                    db.commit()
                    sub = None
                if not sub:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You need an active subscription to this avatar to start a session.",
                    )

            # Pre-flight credit check: subscriber must have a positive balance to start
            from app.services import billing_service as _billing
            balance_info = _billing.get_active_balance(current_user.id, db)
            if balance_info["balance"] <= 0:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="Insufficient credits. Redeem an access code to start a session.",
                )
        # ─────────────────────────────────────────────────────────────────────

        # ── Resolve effective runtime mode ────────────────────────────────────
        session_subscriber_runtime = "avatar"
        if db_session_raw:
            session_subscriber_runtime = getattr(db_session_raw, "subscriber_runtime_mode", "avatar") or "avatar"

        chosen_mode = request_data.get("chosen_mode")
        if session_subscriber_runtime == "choice":
            if not chosen_mode or chosen_mode not in ("avatar", "chat"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="chosen_mode ('avatar' or 'chat') is required when subscriber_runtime_mode is 'choice'.",
                )
            effective_runtime = chosen_mode
        elif chosen_mode and chosen_mode != session_subscriber_runtime:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="chosen_mode does not match the session's subscriber_runtime_mode.",
            )
        else:
            effective_runtime = session_subscriber_runtime
        # ─────────────────────────────────────────────────────────────────────

        session_run = await session_service.start_session_run(
            db, session_id, str(current_user.id), assistant_parameters,
            runtime_mode_used=effective_runtime,
        )
        if not session_run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        # Snapshot the role label from the session row into the run row (reuse already-fetched object)
        if db_session_raw and db_session_raw.role_label:
            session_run.role_at_start = db_session_raw.role_label
            db.commit()

        return SessionRunDetails(
            sessionRunId=str(session_run.session_run_id),
            sessionId=str(session_id),
            userId=str(current_user.id),
            username=current_user.username,
            sessionRunMetadata=session_run.session_run_metadata,
            assistantParameters=AssistantParameters(**session_run.assistant_parameters),
            status=session_run.status,
            courseId=session.courseId,
            courseName=session.courseName,
            className=session.className,
            courseCode=session.courseCode,
            description=session.description,
            duration=session.duration,
            presentationDetails=session.presentationDetails,
            slidesDetails=session.slidesDetails,
            startTime=session_run.start_time,
            endTime=session_run.end_time,
            runtimeModeUsed=effective_runtime,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error starting session run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error starting session run: {e}"
        )

@router.post("/sessions/{session_id}/run/start/guest", response_model=SessionRunDetails)
async def start_session_run(
    session_id: str,
    request_data: dict,
    # current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start a session run for an unauthenticated (shared-link) user.
    Requires GUEST_USER_UUID to be set in settings and the corresponding
    users row to exist in the database.
    """
    try:
        guest_user_uuid = settings.guest_user_uuid
        if not guest_user_uuid:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Guest sessions are not configured (GUEST_USER_UUID not set)",
            )
        guest_user = db.query(User).filter(User.id == guest_user_uuid).first()
        if not guest_user:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Guest sessions are not configured (guest user row missing from database)",
            )
        guest_user_id = str(guest_user.id)
        print(f"Starting session run for session_id: {session_id}")
        assistant_parameters_dict = request_data.get("assistant_parameters")
        
        if not assistant_parameters_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required field: assistant_parameters"
            )
        
        assistant_parameters = AssistantParameters(**assistant_parameters_dict)
        
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        print(f"Session found")
        session_run = await session_service.start_session_run(db, session_id, guest_user_id, assistant_parameters)
        if not session_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return SessionRunDetails(
            sessionRunId=str(session_run.session_run_id),
            sessionId=str(session_id),
            userId=guest_user_id,
            username="guest",
            sessionRunMetadata=session_run.session_run_metadata,
            assistantParameters=AssistantParameters(**session_run.assistant_parameters),
            status=session_run.status,
            courseName=session.courseName,
            className=session.className,
            courseCode=session.courseCode,
            description=session.description,
            duration=session.duration,
            presentationDetails=session.presentationDetails,
            slidesDetails=session.slidesDetails,
            startTime=session_run.start_time,
            endTime=session_run.end_time
        )
    except Exception as e:
        logger.error(f"❌ Error starting session run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error starting session run: {e}"
        )


@router.post("/sessions/{session_id}/run/{session_run_id}/stop", response_model=SessionRunDetails)
async def stop_session_run(
    session_id: str,
    session_run_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Stop a session run and trigger post-session summarization.

    Optional billing fields in request body:
      input_tokens  (int) — realtime input token count reported by the client
      output_tokens (int) — realtime output token count reported by the client
    If present and user is a subscriber, credits are deducted via charge_usage().
    Billing failure is non-fatal: the run is still marked completed.
    """
    try:
        session_run_metadata = request_data.get("session_run_metadata")
        input_tokens = int(request_data.get("input_tokens") or 0)
        output_tokens = int(request_data.get("output_tokens") or 0)

        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        session_run = await session_service.stop_session_run(db, session_id, session_run_id, session_run_metadata)
        if not session_run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        # ── Billing: charge actual token usage for subscribers ─────────────
        if current_user.role == "subscriber" and (input_tokens > 0 or output_tokens > 0):
            try:
                from app.services import billing_service as _billing
                _billing.charge_usage(
                    user_id=current_user.id,
                    operation_type="session_run",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    db=db,
                    session_run_id=session_run.id,
                )
                db.commit()
            except HTTPException as billing_err:
                logger.warning(
                    f"⚠️ Billing charge failed for run {session_run_id} "
                    f"(user={current_user.id}): {billing_err.detail}"
                )
            except Exception as billing_err:
                logger.warning(
                    f"⚠️ Billing charge error for run {session_run_id} "
                    f"(user={current_user.id}): {billing_err}"
                )
        # ──────────────────────────────────────────────────────────────────

        # Trigger background summarization (non-blocking — errors are logged, not raised)
        try:
            db_session_raw = db.query(Session).filter(Session.session_id == session_id).first()
            if db_session_raw:
                import asyncio as _asyncio
                _asyncio.create_task(
                    generate_run_summary(
                        db=db,
                        session=db_session_raw,
                        session_run=session_run,
                        slides_details=db_session_raw.slides_details or [],
                        user_id=current_user.id,
                        avatar_id=db_session_raw.avatar_id,
                    )
                )
        except Exception:
            pass  # Summarization is best-effort

        return SessionRunDetails(
            sessionRunId=str(session_run.session_run_id),
            sessionId=str(session.sessionId),
            userId=str(current_user.id),
            username=current_user.username,
            sessionRunMetadata=session_run.session_run_metadata,
            assistantParameters=AssistantParameters(**session_run.assistant_parameters),
            status=session_run.status,
            courseName=session.courseName,
            className=session.className,
            courseCode=session.courseCode,
            description=session.description,
            duration=session.duration,
            presentationDetails=session.presentationDetails,
            slidesDetails=session.slidesDetails,
            startTime=session_run.start_time,
            endTime=session_run.end_time
        )
    except Exception as e:
        logger.error(f"❌ Error stopping session run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error stopping session run: {e}"
        )

@router.post("/sessions/{session_id}/run/{session_run_id}/stop/guest", response_model=SessionRunDetails)
async def stop_session_run(
    session_id: str,
    session_run_id: str,
    request_data: dict,
    # current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Stop a session run for an unauthenticated (shared-link) user.
    """
    try:
        guest_user_uuid = settings.guest_user_uuid
        if not guest_user_uuid:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Guest sessions are not configured (GUEST_USER_UUID not set)",
            )

        session_run_metadata = request_data.get("session_run_metadata")

        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        session_run = await session_service.stop_session_run(db, session_id, session_run_id, session_run_metadata)
        if not session_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return SessionRunDetails(
            sessionRunId=str(session_run.session_run_id),
            sessionId=str(session.sessionId),
            userId=guest_user_uuid,
            username="guest",
            sessionRunMetadata=session_run.session_run_metadata,
            assistantParameters=AssistantParameters(**session_run.assistant_parameters),
            status=session_run.status,
            courseName=session.courseName,
            className=session.className,
            courseCode=session.courseCode,
            description=session.description,
            duration=session.duration,
            presentationDetails=session.presentationDetails,
            slidesDetails=session.slidesDetails,
            startTime=session_run.start_time,
            endTime=session_run.end_time
        )
    except Exception as e:
        logger.error(f"❌ Error stopping session run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error stopping session run: {e}"
        )
    
@router.get("/sessions/{session_id}/run/{session_run_id}", response_model=SessionRunDetails)
async def get_session_run(
    session_id: str,
    session_run_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a session run by ID
    """
    try:
        logger.info(f"Getting session run for session_id: {session_id} and session_run_id: {session_run_id}")
        session_run = await session_service.get_session_run(db, session_id, session_run_id)
        if not session_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session run not found"
            )
        logger.info(f"Session run found")
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        logger.info(f"Session found")
        user = await session_service.get_user_by_id(db, session_run.user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        return SessionRunDetails(
            sessionRunId=str(session_run.session_run_id),
            sessionId=str(session.sessionId),
            userId=str(user.id),
            username=user.username,
            sessionRunMetadata=session_run.session_run_metadata,
            assistantParameters=AssistantParameters(**session_run.assistant_parameters),
            status=session_run.status,
            courseName=session.courseName,
            className=session.className,
            courseCode=session.courseCode,
            description=session.description,
            duration=session.duration,
            presentationDetails=session.presentationDetails,
            slidesDetails=session.slidesDetails,
            startTime=session_run.start_time,
            endTime=session_run.end_time,
            runtimeModeUsed=getattr(session_run, "runtime_mode_used", None),
        )
    except Exception as e:
        logger.error(f"❌ Error getting session run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting session run: {e}"
        )


@router.get("/session/ephemeral", response_model=EphemeralTokenResponse)
async def get_ephemeral_token(
    session_id: str,
    session_run_id: str,
    current_user: User = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """
    Mint an OpenAI Realtime API ephemeral token for an active session run.

    Two caller types are supported:

    1. Authenticated user — must be the run owner or an admin.
       The frontend attaches `Authorization: Bearer <token>` when a user is
       logged in.

    2. Guest user (shared-link flow) — no token.  Permitted only when the
       session run was started via the guest endpoint, meaning its user_id
       matches the platform's configured GUEST_USER_UUID.  If GUEST_USER_UUID
       is not configured, guest access is denied.
    """
    try:
        session_run = await session_service.get_session_run(db, session_id, session_run_id)
        if not session_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session run not found",
            )

        if session_run.status != SessionRunStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session run is not active",
            )

        # ── Authorization gate ────────────────────────────────────────────────
        run_owner_id = str(session_run.user_id)

        if current_user is not None:
            # Authenticated path: must own the run or be an admin.
            if current_user.role != "admin" and run_owner_id != str(current_user.id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorised to connect to this session run",
                )
        else:
            # Unauthenticated path: only allow guest session runs.
            guest_uuid = settings.guest_user_uuid
            if not guest_uuid or run_owner_id != guest_uuid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                )
        # ─────────────────────────────────────────────────────────────────────

        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )

        # Load raw session row (includes solution slides filtered from public API)
        db_session_raw = db.query(Session).filter(Session.session_id == session_id).first()
        all_slides = db_session_raw.slides_details or [] if db_session_raw else []
        student_slide_list = [s for s in all_slides if s.get('source') != 'solution']
        solution_slide_list = [s for s in all_slides if s.get('source') == 'solution']

        # ── Resolve session mode ──────────────────────────────────────────────
        session_mode: str = "teaching"
        if db_session_raw and hasattr(db_session_raw, "session_mode") and db_session_raw.session_mode:
            session_mode = db_session_raw.session_mode

        # ── Resolve avatar → template_version → prompts ───────────────────────
        conversation_prompt: str | None = None
        teaching_prompt: str | None = None
        examination_prompt: str | None = None
        role_label: str | None = None
        role_context: str | None = None
        if db_session_raw and db_session_raw.avatar_id:
            avatar_row = (
                db.query(Avatar)
                .filter(Avatar.id == db_session_raw.avatar_id)
                .first()
            )
            if not avatar_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="The avatar configured for this session no longer exists. "
                           "Contact the session owner to reassign an avatar before starting a run.",
                )

            # Role from session row (set at session creation)
            role_label = db_session_raw.role_label
            if db_session_raw.selected_role:
                role_context = db_session_raw.selected_role.prompt_context

            # Resolve template version: frozen at avatar creation → current published → legacy
            version: AvatarTemplateVersion | None = None
            if avatar_row.template_version_id:
                version = db.query(AvatarTemplateVersion).filter(
                    AvatarTemplateVersion.id == avatar_row.template_version_id
                ).first()
            # Fall back to current published version
            if not version and avatar_row.template_id:
                tmpl = db.query(AvatarTemplate).filter(
                    AvatarTemplate.id == avatar_row.template_id
                ).first()
                if tmpl and tmpl.current_version_id:
                    version = db.query(AvatarTemplateVersion).filter(
                        AvatarTemplateVersion.id == tmpl.current_version_id
                    ).first()
                # Legacy column fallback
                if not version and tmpl:
                    conversation_prompt = (tmpl.hidden_system_prompt or "").strip() or None
            if version:
                conversation_prompt = (version.conversation_prompt or "").strip() or None
                teaching_prompt = (getattr(version, "teaching_prompt", None) or "").strip() or None
                examination_prompt = (getattr(version, "examination_prompt", None) or "").strip() or None

        # ── Session summary + memories ────────────────────────────────────────
        session_summary = get_recent_session_summary(
            db, session_id, exclude_run_id=session_run_id
        )
        memories: list = []
        if db_session_raw:
            memories = get_user_memories(
                db,
                user_id=db_session_raw.user_id,
                avatar_id=db_session_raw.avatar_id,
            )

        token_data = await openai_service.generate_ephemeral_token(
            session_run.assistant_parameters,
            student_slide_list,
            solution_slide_list or None,
            conversation_prompt=conversation_prompt,
            teaching_prompt=teaching_prompt,
            examination_prompt=examination_prompt,
            session_mode=session_mode,
            role_label=role_label,
            role_context=role_context,
            session_summary=session_summary,
            memories=memories,
        )
        return EphemeralTokenResponse(client_secret=token_data["client_secret"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate ephemeral token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate ephemeral token: {str(e)}",
        )


@router.get("/sessions", response_model=SessionsListResponse)
async def get_sessions(
    page: int = Query(1, ge=1, description="Page number for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Number of sessions per page"),
    session_status: Optional[str] = Query(None, regex="^(active|completed|draft)$", description="Filter by session status", alias="status"),
    sort: str = Query("created_desc", regex="^(created_desc|created_asc|updated_desc|updated_asc)$", description="Sort order"),
    avatar_id: Optional[str] = Query(None, description="Filter sessions by avatar_id"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get paginated list of sessions for the authenticated user.
    Pass avatar_id to scope results to sessions that use a specific avatar.
    """
    try:
        sessions, pagination = await session_service.get_sessions_paginated(
            db=db,
            user_id=str(current_user.id),
            page=page,
            limit=limit,
            status=session_status,
            sort=sort,
            avatar_id=avatar_id,
        )
        
        return SessionsListResponse(
            sessions=sessions,
            pagination=pagination
        )
    except Exception as e:
        logger.error(f"❌ Error getting sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting sessions: {e}"
        )

@router.get("/sessions/{session_id}/runs", response_model=SessionRunsListResponse)
async def get_session_runs(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all runs for a specific session
    """
    try:
        runs, total = await session_service.get_session_runs(
            db=db,
            session_id=session_id,
            user_id=str(current_user.id)
        )
        
        return SessionRunsListResponse(
            runs=runs,
            total=total
        )
    except Exception as e:
        logger.error(f"❌ Error getting session runs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting session runs: {e}"
        )
    
@router.post("/sessions/{session_id}/slides/{slide_id}/vision", response_model=SessionDetails)
async def update_slide_vision(
    session_id: str,
    slide_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        for slide in session.slidesDetails:
            logger.info(f"Slide ID: {slide.id}")
            if slide.id == int(slide_id):
                logger.info(f"Updating slide vision for slide_id: {slide_id}")
                slide.visionInstructions = request_data.get('visionInstructions')
                slide.visionModel = request_data.get('visionModel')
                logger.info(f"Slide vision instructions: {slide.visionInstructions}")
                
                # Handle both S3 URLs and local file paths
                logger.info(f"Slide image path: {slide.imagePath}")
                
                # Check if the path is an S3 URL
                if slide.imagePath.startswith('http://') or slide.imagePath.startswith('https://'):
                    # Download image from S3 URL
                    logger.info(f"Downloading image from S3 URL: {slide.imagePath}")
                    try:
                        response = requests.get(slide.imagePath, timeout=30)
                        response.raise_for_status()
                        slide_image = Image.open(BytesIO(response.content))
                        logger.info(f"Successfully downloaded image from S3")
                    except requests.RequestException as e:
                        logger.error(f"Failed to download image from S3: {e}")
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Failed to download slide image from S3: {str(e)}"
                        )
                else:
                    # Handle local file paths
                    if slide.imagePath.startswith('/uploads/'):
                        # Remove the leading '/uploads/' and use the upload_dir setting
                        relative_path = slide.imagePath[9:]  # Remove '/uploads/'
                        actual_file_path = Path(settings.upload_dir) / relative_path
                    else:
                        # Fallback: try the path as-is, removing leading '/'
                        actual_file_path = Path(slide.imagePath.lstrip('/'))
                    
                    logger.info(f"Local file path: {actual_file_path}")
                    
                    if not actual_file_path.exists():
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Slide image file not found: {actual_file_path}"
                        )
                    
                    slide_image = Image.open(actual_file_path)
                
                # Process the slide with vision API
                slide_details = await openai_service.process_slide_with_vision(slide_image, slide.visionInstructions, slide.visionModel)
                slide.content = slide_details.get('content')
                slide.title = slide_details.get('title')
                logger.info(f"Successfully updated slide vision for slide {slide_id}")
                break
        # Convert SlideData objects to dictionaries for JSON serialization
        slides_dict_list = []
        for slide in session.slidesDetails:
            slides_dict_list.append(slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict())
        
        updated_session = await session_service.update_session_slides(db, session_id, slides_dict_list)
        if not updated_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return updated_session

    except Exception as e:
        logger.error(f"❌ Error updating slide vision: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating slide vision: {e}"
        )
    
@router.put("/sessions/{session_id}/slides/{slide_id}/content", response_model=SessionDetails)
async def update_slide_content(
    session_id: str,
    slide_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        print(f"Updating slide content for session_id: {session_id} and slide_id: {slide_id}")
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        for slide in session.slidesDetails:
            if slide.id == int(slide_id):
                slide.content = request_data.get('content')
                slide.title = request_data.get('title')
                break
        # Convert SlideData objects to dictionaries for JSON serialization
        slides_dict_list = []
        for slide in session.slidesDetails:
            slides_dict_list.append(slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict())
        
        updated_session = await session_service.update_session_slides(db, session_id, slides_dict_list)
        if not updated_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return updated_session
    except Exception as e:
        logger.error(f"❌ Error updating slide content: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating slide content: {e}"
        )

@router.post("/sessions/{session_id}/slides/add", response_model=SessionDetails)
async def add_new_slide(
    session_id: str,
    slide_image: UploadFile = File(...),
    vision_instructions: str = Form(None),
    vision_model: str = Form("gpt-4o"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        logger.info(f"Adding new slide to session: {session_id}")
        
        # Get session
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        # Read image file
        image_content = await slide_image.read()
        slide_image_pil = Image.open(BytesIO(image_content))
        
        # Determine next slide number
        max_slide_number = max([slide.slideNumber for slide in session.slidesDetails]) if session.slidesDetails else 0
        new_slide_number = max_slide_number + 1
        
        # Create session-specific directory paths
        session_dir = Path(settings.upload_dir) / session_id
        session_slides_dir = session_dir / "slides"
        session_slides_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filenames
        image_filename = f"slide_{new_slide_number - 1}.png"
        thumbnail_filename = f"thumb_{new_slide_number - 1}.png"
        
        # Save full-size image
        full_image_path = session_slides_dir / image_filename
        slide_image_pil.save(full_image_path, 'PNG')
        logger.info(f"Saved slide image: {full_image_path}")
        
        # Create and save thumbnail
        thumbnail_image = slide_image_pil.copy()
        thumbnail_image.thumbnail((256, 192), Image.Resampling.LANCZOS)
        thumbnail_path = session_slides_dir / thumbnail_filename
        thumbnail_image.save(thumbnail_path, 'PNG')
        logger.info(f"Saved thumbnail: {thumbnail_path}")
        
        # Handle cloud storage or local paths
        if settings.use_cloud_storage:
            from app.services.cloud_storage_service import cloud_storage
            
            # Convert images to bytes
            full_image_buffer = BytesIO()
            slide_image_pil.save(full_image_buffer, format='PNG')
            full_image_bytes = full_image_buffer.getvalue()
            
            thumbnail_buffer = BytesIO()
            thumbnail_image.save(thumbnail_buffer, format='PNG')
            thumbnail_bytes = thumbnail_buffer.getvalue()
            
            # Upload to S3
            full_s3_key, full_public_url = await cloud_storage.upload_image(
                image_data=full_image_bytes,
                file_path=str(full_image_path),
                content_type='image/png',
                metadata={
                    'session_id': session_id,
                    'slide_number': str(new_slide_number),
                    'image_type': 'full_size'
                }
            )
            
            thumbnail_s3_key, thumbnail_public_url = await cloud_storage.upload_image(
                image_data=thumbnail_bytes,
                file_path=str(thumbnail_path),
                content_type='image/png',
                metadata={
                    'session_id': session_id,
                    'slide_number': str(new_slide_number),
                    'image_type': 'thumbnail'
                }
            )
            
            image_path = full_public_url
            thumbnail_path_url = thumbnail_public_url
        else:
            image_path = f"/uploads/{session_id}/slides/{image_filename}"
            thumbnail_path_url = f"/uploads/{session_id}/slides/{thumbnail_filename}"
        
        # Process with vision API
        if not vision_instructions:
            vision_instructions = "You are an expert academic content analyst. Extract and describe the complete content of this examination slide for use by an AI oral examiner. Transcribe all text, equations (plain-text notation), code, diagrams (structure, axes, labels, key values), and tables. Be thorough and exact — this content will be used to generate examination questions and evaluate student responses."
        
        slide_details = await openai_service.process_slide_with_vision(
            slide_image_pil, 
            vision_instructions, 
            vision_model
        )
        
        # Create new slide object
        new_slide = {
            "id": new_slide_number,
            "slideNumber": new_slide_number,
            "title": slide_details.get('title'),
            "content": slide_details.get('content'),
            "imagePath": image_path,
            "thumbnailPath": thumbnail_path_url,
            "visionInstructions": vision_instructions,
            "visionModel": vision_model
        }
        
        # Add to session slides
        slides_dict_list = []
        for slide in session.slidesDetails:
            slides_dict_list.append(slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict())
        slides_dict_list.append(new_slide)
        
        # Update session
        updated_session = await session_service.update_session_slides(db, session_id, slides_dict_list)
        logger.info(f"✅ Successfully added new slide {new_slide_number} to session {session_id}")
        
        return updated_session
        
    except Exception as e:
        logger.error(f"❌ Error adding new slide: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error adding new slide: {e}"
        )

@router.delete("/sessions/{session_id}/slides/{slide_id}", response_model=SessionDetails)
async def delete_slide(
    session_id: str,
    slide_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        logger.info(f"Deleting slide {slide_id} from session: {session_id}")
        
        # Get session
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        # Find and remove the slide
        slide_to_delete = None
        remaining_slides = []
        for slide in session.slidesDetails:
            if slide.id == int(slide_id):
                slide_to_delete = slide
            else:
                remaining_slides.append(slide)
        
        if not slide_to_delete:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Slide not found"
            )
        
        # Reorganize slide numbers
        slides_dict_list = []
        for idx, slide in enumerate(remaining_slides, start=1):
            slide_dict = slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict()
            slide_dict['id'] = idx
            slide_dict['slideNumber'] = idx
            slides_dict_list.append(slide_dict)
        
        # Update session
        updated_session = await session_service.update_session_slides(db, session_id, slides_dict_list)
        logger.info(f"✅ Successfully deleted slide and reorganized slide numbers")
        
        return updated_session
        
    except Exception as e:
        logger.error(f"❌ Error deleting slide: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting slide: {e}"
        )

@router.put("/sessions/{session_id}/slides/{slide_id}/replace-image", response_model=SessionDetails)
async def replace_slide_image(
    session_id: str,
    slide_id: str,
    slide_image: UploadFile = File(...),
    vision_instructions: str = Form(None),
    vision_model: str = Form("gpt-4o"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        logger.info(f"Replacing image for slide {slide_id} in session: {session_id}")
        
        # Get session
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        # Find the slide
        target_slide = None
        for slide in session.slidesDetails:
            if slide.id == int(slide_id):
                target_slide = slide
                break
        
        if not target_slide:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Slide not found"
            )
        
        # Read new image file
        image_content = await slide_image.read()
        slide_image_pil = Image.open(BytesIO(image_content))
        
        # Create session-specific directory paths
        session_dir = Path(settings.upload_dir) / session_id
        session_slides_dir = session_dir / "slides"
        session_slides_dir.mkdir(parents=True, exist_ok=True)
        
        # Use existing filenames based on slide number
        image_filename = f"slide_{target_slide.slideNumber - 1}.png"
        thumbnail_filename = f"thumb_{target_slide.slideNumber - 1}.png"
        
        # Save full-size image (overwrite existing)
        full_image_path = session_slides_dir / image_filename
        slide_image_pil.save(full_image_path, 'PNG')
        logger.info(f"Replaced slide image: {full_image_path}")
        
        # Create and save thumbnail
        thumbnail_image = slide_image_pil.copy()
        thumbnail_image.thumbnail((256, 192), Image.Resampling.LANCZOS)
        thumbnail_path = session_slides_dir / thumbnail_filename
        thumbnail_image.save(thumbnail_path, 'PNG')
        logger.info(f"Replaced thumbnail: {thumbnail_path}")
        
        # Handle cloud storage or local paths
        if settings.use_cloud_storage:
            from app.services.cloud_storage_service import cloud_storage
            
            # Convert images to bytes
            full_image_buffer = BytesIO()
            slide_image_pil.save(full_image_buffer, format='PNG')
            full_image_bytes = full_image_buffer.getvalue()
            
            thumbnail_buffer = BytesIO()
            thumbnail_image.save(thumbnail_buffer, format='PNG')
            thumbnail_bytes = thumbnail_buffer.getvalue()
            
            # Upload to S3 (overwrite existing)
            full_s3_key, full_public_url = await cloud_storage.upload_image(
                image_data=full_image_bytes,
                file_path=str(full_image_path),
                content_type='image/png',
                metadata={
                    'session_id': session_id,
                    'slide_number': str(target_slide.slideNumber),
                    'image_type': 'full_size'
                }
            )
            
            thumbnail_s3_key, thumbnail_public_url = await cloud_storage.upload_image(
                image_data=thumbnail_bytes,
                file_path=str(thumbnail_path),
                content_type='image/png',
                metadata={
                    'session_id': session_id,
                    'slide_number': str(target_slide.slideNumber),
                    'image_type': 'thumbnail'
                }
            )
            
            image_path = full_public_url
            thumbnail_path_url = thumbnail_public_url
        else:
            image_path = f"/uploads/{session_id}/slides/{image_filename}"
            thumbnail_path_url = f"/uploads/{session_id}/slides/{thumbnail_filename}"
        
        # Use provided vision instructions or existing ones
        if not vision_instructions:
            vision_instructions = target_slide.visionInstructions or "You are an expert academic content analyst. Extract and describe the complete content of this examination slide for use by an AI oral examiner. Transcribe all text, equations (plain-text notation), code, diagrams (structure, axes, labels, key values), and tables. Be thorough and exact — this content will be used to generate examination questions and evaluate student responses."
        
        # Process with vision API
        slide_details = await openai_service.process_slide_with_vision(
            slide_image_pil,
            vision_instructions,
            vision_model
        )
        
        # Update slide
        target_slide.imagePath = image_path
        target_slide.thumbnailPath = thumbnail_path_url
        target_slide.title = slide_details.get('title')
        target_slide.content = slide_details.get('content')
        target_slide.visionInstructions = vision_instructions
        target_slide.visionModel = vision_model
        
        # Convert slides to dictionaries
        slides_dict_list = []
        for slide in session.slidesDetails:
            slides_dict_list.append(slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict())
        
        # Update session
        updated_session = await session_service.update_session_slides(db, session_id, slides_dict_list)
        logger.info(f"✅ Successfully replaced image and regenerated content for slide {slide_id}")
        
        return updated_session
        
    except Exception as e:
        logger.error(f"❌ Error replacing slide image: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error replacing slide image: {e}"
        )

@router.put("/sessions/{session_id}/slides/reorder", response_model=SessionDetails)
async def reorder_slides(
    session_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        logger.info(f"Reordering slides for session: {session_id}")
        
        # Get session
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        slide_order = request_data.get('slideOrder', [])
        if not slide_order:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slideOrder is required"
            )
        
        # Create a mapping of old IDs to slides
        slides_by_id = {}
        for slide in session.slidesDetails:
            slides_by_id[slide.id] = slide
        
        # Reorder slides
        reordered_slides = []
        for new_position, old_id in enumerate(slide_order, start=1):
            if old_id not in slides_by_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid slide ID: {old_id}"
                )
            
            slide = slides_by_id[old_id]
            slide_dict = slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict()
            slide_dict['id'] = new_position
            slide_dict['slideNumber'] = new_position
            reordered_slides.append(slide_dict)
        
        # Update session
        updated_session = await session_service.update_session_slides(db, session_id, reordered_slides)
        logger.info(f"✅ Successfully reordered slides")
        
        return updated_session
        
    except Exception as e:
        logger.error(f"❌ Error reordering slides: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reordering slides: {e}"
        )


@router.post("/ai/answer")
async def ai_answer(request_data: dict):
    """
    Proxy endpoint for OpenAI Chat Completions API.
    Used by the frontend for non-realtime AI calls (slide analysis, etc).
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_data,
            )
        return response.json()
    except Exception as e:
        logger.error(f"❌ Error proxying AI answer: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI answer proxy failed: {str(e)}"
        )

@router.post("/sessions/{session_id}/search")
async def search_session_knowledge(
    session_id: str,
    request: SearchRequest,
    current_user: User = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """
    Search session slides and optionally course materials for relevant chunks.
    """
    try:
        chunks = retrieve_context(session_id, request.query, top_k=5, db=db, course_id=request.course_id)
        return {"results": chunks}
    except Exception as e:
        logger.error(f"Error searching knowledge: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching knowledge: {e}"
        )
