import logging
import uuid
from datetime import datetime
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
    Course, CourseStudent, PublisherAvatarProfile, AvatarConfiguration,
)
from app.database.models.feedback import SessionPersonaSwitch
from app.services.summarization_service import (
    generate_run_summary, get_recent_session_summary, get_user_memories,
)
from app.schemas.schemas import (
    SessionDetails, SlideData, PresentationData, AssistantParameters,
    SessionRunDetails, EphemeralTokenResponse, SessionUpdateDetails,
    SessionsListResponse, SessionRunsListResponse, SessionCreateRequest,
    SearchKnowledgeRequest, SearchKnowledgeResponse, KnowledgeChunk,
    FlagTopicRequest, FlagTopicResponse,
    PatchSessionRoleRequest,
    SessionFeedbackRequest, SessionFeedbackResponse,
    TranscriptFeedbackRequest, TranscriptFeedbackResponse,
)
from app.services.file_processor import FileProcessor
from app.services.openai_service import OpenAIService
from app.services.session_service import SessionService
from app.services.rag_service import ingest_session_document_background, retrieve_context
from app.services import session_resolution_service
from app.services.avatar_variant_service import resolve_default_variant, build_variant_snapshot
from app.services.prompt_resolution_service import PromptResolutionService
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
    presentation: Optional[UploadFile] = File(None),
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

        # Subscriber session-creation gates (enrollment / allow_subscriber_sessions)
        # are temporarily disabled — subscribers can freely create their own sessions.

        source = session_details_dict.get("source", "upload")

        # Generate session ID (needed by both branches for output image paths)
        logger.info(f"🆔 Generating session ID")
        session_id = session_service.generate_session_id()
        logger.info(f"✅ Session ID generated: {session_id}")

        if source == "upload":
            # ── Upload branch: existing behaviour ──────────────────────────────
            if presentation is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="presentation file is required when source is 'upload'"
                )

            logger.info(f"📂 Reading file content: {presentation.filename}")
            file_content = await presentation.read()
            logger.info(f"✅ File read successfully, size: {len(file_content)} bytes")

            if len(file_content) > settings.max_file_size:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum allowed size is {settings.max_file_size // (1024 * 1024)} MB. Your file is {len(file_content) / (1024 * 1024):.1f} MB."
                )

            logger.info(f"🔍 Validating file: {presentation.filename}")
            is_valid, error_message = file_processor.validate_file(file_content, presentation.filename)
            if not is_valid:
                logger.error(f"❌ File validation failed: {error_message}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File validation failed: {error_message}"
                )

            file_path = await file_processor.save_uploaded_file(file_content, presentation.filename, session_id)
            logger.info(f"✅ File saved to: {file_path}")

            presentation_details_dict = {
                "filename": presentation.filename,
                "filePath": file_path,
                "fileSize": len(file_content),
                "fileType": Path(presentation.filename).suffix.lower(),
            }

            student_slides = await _process_upload(
                file_processor, openai_service,
                file_path, presentation.filename, session_id,
                source="student",
                vision_instructions=session_details_dict.get('visionInstructions'),
                vision_model=session_details_dict.get('visionModel'),
            )
            logger.info(f"✅ Student slides processed ({len(student_slides)} slides)")

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

        elif source == "assessment":
            # ── Assessment branch: process files from an existing autograder submission ──
            # NOTE: autograder files are local-disk only (no R2/S3). This branch
            # requires the session API and autograder to share the same filesystem.
            submission_id_str = session_details_dict.get("submissionId")
            if not submission_id_str:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="submissionId is required in sessionDetails when source is 'assessment'"
                )
            try:
                submission_uuid = uuid.UUID(submission_id_str)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="submissionId must be a valid UUID"
                )

            from app.database.models.autograder import AutograderSubmission
            submission = db.query(AutograderSubmission).filter(
                AutograderSubmission.id == submission_uuid
            ).first()
            if not submission:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Autograder submission not found"
                )
            if submission.submitted_by != current_user.id and current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have access to this submission"
                )

            handwritten_path = submission.handwritten_file_path
            webassign_path = submission.webassign_file_path
            if not handwritten_path or not Path(handwritten_path).exists():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Handwritten PDF for this submission is not available on disk"
                )
            if not webassign_path or not Path(webassign_path).exists():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="WebAssign PDF for this submission is not available on disk"
                )

            handwritten_filename = submission.handwritten_filename or Path(handwritten_path).name
            webassign_filename = submission.webassign_filename or Path(webassign_path).name

            presentation_details_dict = {
                "filename": handwritten_filename,
                "filePath": handwritten_path,
                "fileSize": 0,
                "fileType": Path(handwritten_path).suffix.lower(),
            }

            # Inject submissionId into assistantParameters JSONB so the
            # ephemeral endpoint can retrieve grading feedback at session start
            ap = session_details_dict.get("assistantParameters") or {}
            ap["submissionId"] = submission_id_str
            session_details_dict["assistantParameters"] = ap

            handwritten_slides = await _process_upload(
                file_processor, openai_service,
                handwritten_path, handwritten_filename, session_id,
                source="handwritten",
                vision_instructions=session_details_dict.get('visionInstructions'),
                vision_model=session_details_dict.get('visionModel'),
            )
            logger.info(f"✅ Handwritten slides processed ({len(handwritten_slides)} slides)")

            question_slides = await _process_upload(
                file_processor, openai_service,
                webassign_path, webassign_filename, session_id,
                source="question",
                vision_instructions=session_details_dict.get('visionInstructions'),
                vision_model=session_details_dict.get('visionModel'),
            )
            logger.info(f"✅ Question slides processed ({len(question_slides)} slides)")

            slides_details = handwritten_slides + question_slides

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid source value: '{source}'. Must be 'upload' or 'assessment'."
            )

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

@router.get("/sessions/{session_id}/eligibility")
async def check_session_eligibility(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lightweight pre-flight check for subscribers: returns whether the user can
    start this session and a list of human-readable blocking issues.
    Publishers/admins always get eligible=True.
    """
    db_session = db.query(Session).filter(Session.session_id == session_id).first()
    if not db_session:
        return {"eligible": False, "issues": [{"code": "not_found", "message": "Session not found."}]}

    # Subscriber gates (course opt-in, enrollment, published-only, avatar
    # subscription, credit balance) are temporarily disabled — every
    # subscriber is eligible to start any session.
    return {"eligible": True, "issues": []}


@router.patch("/sessions/{session_id}/publish")
async def set_session_published(
    session_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Set is_published on a session. Body: {"is_published": true|false}
    Only the session owner or an admin may call this.
    """
    is_published = request_data.get("is_published")
    if not isinstance(is_published, bool):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body must contain {'is_published': true|false}",
        )

    db_session = db.query(Session).filter(Session.session_id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if current_user.role != "admin" and str(db_session.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only modify your own sessions",
        )

    db_session.is_published = is_published
    db_session.updated_at = datetime.utcnow()
    db.commit()
    return {"session_id": session_id, "is_published": is_published}


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
    request_data: PatchSessionRoleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update the selected role and/or active variant on a session (Wave 4 — R76).

    Accepts:
      role_id    (str, optional) — AvatarTemplateRole UUID; updates session.selected_role_id
      variant_id (str, optional) — AvatarVariant UUID; switches the active persona and
                                   logs a SessionPersonaSwitch row when session_run_id is
                                   also supplied
      session_run_id (str, optional) — active run ID; required to log persona switch

    At least one of role_id or variant_id must be provided.
    """
    try:
        db_session = db.query(Session).filter(Session.session_id == session_id).first()
        if not db_session:
            raise HTTPException(status_code=404, detail="Session not found")
        if current_user.role != "admin" and str(db_session.user_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="Not authorised")

        role_id = request_data.role_id
        variant_id = request_data.variant_id  # UUID | None — validated by Pydantic
        session_run_id_str = request_data.session_run_id

        if not role_id and not variant_id:
            raise HTTPException(status_code=400, detail="role_id or variant_id is required")

        response: dict = {"sessionId": session_id}

        # ── Template role update (existing behaviour, backward compatible) ──────
        if role_id:
            role_row = db.query(AvatarTemplateRole).filter(
                AvatarTemplateRole.id == role_id,
                AvatarTemplateRole.is_enabled == True,
            ).first()
            if not role_row:
                raise HTTPException(status_code=404, detail="Role not found or disabled")
            db_session.selected_role_id = role_row.id
            db_session.role_label = role_row.name
            response["roleId"] = str(role_row.id)
            response["roleLabel"] = role_row.name

        # ── Variant switch (Wave 4 — R76) ────────────────────────────────────────
        if variant_id:
            if not db_session.avatar_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Session has no avatar — variant switching requires an avatar.",
                )

            # Subscribers may be restricted from switching variants
            if current_user.role == "subscriber":
                avatar_row = db.query(Avatar).filter(Avatar.id == db_session.avatar_id).first()
                if avatar_row and not avatar_row.allow_subscriber_variant_switch:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Variant switching is not permitted for subscribers on this avatar.",
                    )

            from app.services.avatar_variant_service import get_variant
            variant = get_variant(
                avatar_id=db_session.avatar_id,
                variant_id=variant_id,
                db=db,
            )

            # Log persona switch when an active run is supplied
            if session_run_id_str:
                run = db.query(SessionRun).filter(
                    SessionRun.session_id == db_session.id,
                    SessionRun.session_run_id == session_run_id_str,
                ).first()
                if run:
                    from datetime import datetime as _dt
                    switch = SessionPersonaSwitch(
                        session_run_id=run.id,
                        user_id=current_user.id,
                        from_persona=db_session.role_label or None,
                        to_persona=variant.name,
                        switched_at=_dt.utcnow(),
                    )
                    db.add(switch)

            response["variantId"] = str(variant.id)
            response["variantName"] = variant.name
            response["variantLanguage"] = variant.language
            response["variantSnapshot"] = build_variant_snapshot(variant)

        db.commit()
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating session role/variant: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/sessions/{session_id}/runs/{session_run_id}/search-knowledge",
    response_model=SearchKnowledgeResponse,
)
async def search_knowledge(
    session_id: str,
    session_run_id: str,
    body: SearchKnowledgeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Live RAG knowledge retrieval during an active session run (Wave 4 — R67).

    Queries the session's embedded slide content and any indexed course materials.
    The caller must own the session run (or be an admin).
    """
    try:
        session_run = await session_service.get_session_run(db, session_id, session_run_id)
        if not session_run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found")

        if current_user.role != "admin" and str(session_run.user_id) != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorised")

        db_session_raw = db.query(Session).filter(Session.session_id == session_id).first()
        if not db_session_raw:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        chunks = retrieve_context(
            session_id=db_session_raw.id,
            query=body.query,
            top_k=body.top_k,
            db=db,
            course_id=db_session_raw.course_id,
        )

        results = [
            KnowledgeChunk(
                slide_number=c.get("slide_number"),
                chunk_index=c.get("chunk_index"),
                content=c.get("content", ""),
                score=float(c.get("score", 0.0)),
                source=c.get("source", "slide"),
            )
            for c in chunks
        ]

        return SearchKnowledgeResponse(query=body.query, results=results, total=len(results))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error searching knowledge: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post(
    "/sessions/{session_id}/runs/{session_run_id}/flag-topic",
    response_model=FlagTopicResponse,
)
async def flag_topic(
    session_id: str,
    session_run_id: str,
    body: FlagTopicRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Flag a topic encountered during a session run for publisher review (Wave 4 — R75).

    The caller must own the session run (or be an admin).
    """
    try:
        session_run = await session_service.get_session_run(db, session_id, session_run_id)
        if not session_run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found")

        if current_user.role != "admin" and str(session_run.user_id) != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorised")

        from datetime import datetime as _dt
        flagged_at = _dt.utcnow()

        logger.info(
            "Topic flagged for review — session=%s run=%s user=%s topic=%r",
            session_id, session_run_id, current_user.id, body.topic,
        )

        return FlagTopicResponse(
            session_run_id=session_run_id,
            topic=body.topic,
            flagged_at=flagged_at,
            message="Topic flagged for review.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error flagging topic: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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
        _avatar_resolution = None  # populated below for subscribers (Wave 4 — R52)

        # Subscriber gates (enrollment, allow_subscriber_sessions, published-only,
        # avatar subscription, credit balance) are temporarily disabled — subscribers
        # can freely create and run their own realtime sessions.
        if current_user.role == "subscriber" and not db_session_raw:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
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

        # R72 (Wave 4): write default avatar variant to the run row.
        # For subscribers, use the pre-resolved result from Gate 4.
        # For publishers/admins, resolve fresh from session.avatar_id.
        try:
            if _avatar_resolution and _avatar_resolution.get("variant_id"):
                session_run.avatar_variant_id = _avatar_resolution["variant_id"]
                session_run.variant_snapshot = _avatar_resolution["variant_snapshot"]
                db.commit()
            elif not _avatar_resolution and db_session_raw and db_session_raw.avatar_id:
                _dv = resolve_default_variant(db_session_raw.avatar_id, db)
                if _dv:
                    session_run.avatar_variant_id = _dv.id
                    session_run.variant_snapshot = build_variant_snapshot(_dv, db)
                    db.commit()
        except Exception as _ve:
            logger.warning("Could not snapshot avatar variant for run %s: %s", session_run.session_run_id, _ve)

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
    Stop a session run. Dispatches Celery tasks for summary, progress, and quiz (W6).

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

        # W6: delegate billing + all async post-session tasks to lifecycle service
        db_session_raw = db.query(Session).filter(Session.session_id == session_id).first()
        if db_session_raw:
            try:
                from app.services.session_lifecycle_service import run_post_session_tasks
                run_post_session_tasks(
                    db=db,
                    session=db_session_raw,
                    session_run=session_run,
                    user_id=current_user.id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    is_subscriber=(current_user.role == "subscriber"),
                )
            except Exception as lifecycle_err:
                logger.warning("Post-session lifecycle error for run %s: %s", session_run_id, lifecycle_err)

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

@router.patch("/sessions/{session_id}/run/{session_run_id}/transition")
async def transition_session_run(
    session_id: str,
    session_run_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Record a mid-run mode switch (e.g. "Continue in Chat" from a realtime
    voice session) on the SessionRun. Metadata-only bookkeeping — does not
    stop or otherwise affect the run's active status. Called fire-and-forget
    by the frontend, so failures here must never block the client-side
    transition to chat mode.

    Body: { runtime_mode_used: "chat" }
    """
    try:
        runtime_mode_used = request_data.get("runtime_mode_used", "chat")
        session_run = await session_service.transition_session_run(
            db, session_id, session_run_id, runtime_mode_used
        )
        if not session_run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found")
        return {"sessionRunId": session_run_id, "runtimeModeUsed": session_run.runtime_mode_used}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error transitioning session run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error transitioning session run: {e}"
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


# ── W6: Feedback endpoints (R84, R85) ────────────────────────────────────────

@router.post(
    "/sessions/{session_id}/runs/{session_run_id}/feedback",
    response_model=SessionFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_session_feedback(
    session_id: str,
    session_run_id: str,
    body: SessionFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit end-of-session feedback for a completed run (R84).

    One feedback record per session run per user (unique constraint on session_run_id).
    A second submission returns the existing record without error.
    """
    import uuid as _uuid
    from sqlalchemy.exc import IntegrityError
    from app.database.models.feedback import SessionFeedback

    session_run = (
        db.query(SessionRun)
        .filter(SessionRun.session_run_id == session_run_id)
        .first()
    )
    if not session_run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found")

    # Validate that the run belongs to the session named in the path
    parent_session = db.query(Session).filter(Session.id == session_run.session_id).first()
    if not parent_session or parent_session.session_id != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found")

    # Idempotent: return existing if already submitted
    existing = (
        db.query(SessionFeedback)
        .filter(SessionFeedback.session_run_id == session_run.id)
        .first()
    )
    if existing:
        return SessionFeedbackResponse(
            id=existing.id,
            session_run_id=existing.session_run_id,
            user_id=existing.user_id,
            overall_rating=existing.overall_rating,
            clarity_rating=existing.clarity_rating,
            helpfulness_rating=existing.helpfulness_rating,
            engagement_rating=existing.engagement_rating,
            comments=existing.comments,
            tags=existing.tags,
            created_at=existing.created_at,
        )

    feedback = SessionFeedback(
        id=_uuid.uuid4(),
        session_run_id=session_run.id,
        user_id=current_user.id,
        avatar_id=parent_session.avatar_id,
        overall_rating=body.overall_rating,
        clarity_rating=body.clarity_rating,
        helpfulness_rating=body.helpfulness_rating,
        engagement_rating=body.engagement_rating,
        comments=body.comments,
        tags=body.tags,
    )
    db.add(feedback)
    try:
        db.commit()
        db.refresh(feedback)
    except IntegrityError:
        db.rollback()
        # Concurrent insert won the race — return the existing row
        existing = (
            db.query(SessionFeedback)
            .filter(SessionFeedback.session_run_id == session_run.id)
            .first()
        )
        if not existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Feedback already submitted")
        feedback = existing

    return SessionFeedbackResponse(
        id=feedback.id,
        session_run_id=feedback.session_run_id,
        user_id=feedback.user_id,
        overall_rating=feedback.overall_rating,
        clarity_rating=feedback.clarity_rating,
        helpfulness_rating=feedback.helpfulness_rating,
        engagement_rating=feedback.engagement_rating,
        comments=feedback.comments,
        tags=feedback.tags,
        created_at=feedback.created_at,
    )


@router.post(
    "/sessions/{session_id}/runs/{session_run_id}/transcript-feedback",
    response_model=TranscriptFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_transcript_feedback(
    session_id: str,
    session_run_id: str,
    body: TranscriptFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit inline per-turn transcript feedback (R85).

    Multiple turns can be flagged per run; turn_index identifies the specific turn.
    A subscriber can update an existing rating for the same turn by submitting again —
    the existing row is updated in place.
    """
    from app.database.models.feedback import TranscriptFeedback

    session_run = (
        db.query(SessionRun)
        .filter(SessionRun.session_run_id == session_run_id)
        .first()
    )
    if not session_run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found")

    # Validate that the run belongs to the session named in the path
    parent_session = db.query(Session).filter(Session.id == session_run.session_id).first()
    if not parent_session or parent_session.session_id != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found")

    existing = (
        db.query(TranscriptFeedback)
        .filter(
            TranscriptFeedback.session_run_id == session_run.id,
            TranscriptFeedback.user_id == current_user.id,
            TranscriptFeedback.turn_index == body.turn_index,
        )
        .first()
    )

    if existing:
        existing.rating = body.rating
        existing.comment = body.comment
        db.commit()
        db.refresh(existing)
        row = existing
    else:
        import uuid as _uuid
        row = TranscriptFeedback(
            id=_uuid.uuid4(),
            session_run_id=session_run.id,
            user_id=current_user.id,
            turn_index=body.turn_index,
            rating=body.rating,
            comment=body.comment,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

    return TranscriptFeedbackResponse(
        id=row.id,
        session_run_id=row.session_run_id,
        user_id=row.user_id,
        turn_index=row.turn_index,
        rating=row.rating,
        comment=row.comment,
        created_at=row.created_at,
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

        # ── Publisher teaching persona ─────────────────────────────────────────
        refined_prompt: str | None = None
        if db_session_raw and db_session_raw.avatar_id:
            avatar_profile = (
                db.query(PublisherAvatarProfile)
                .filter(PublisherAvatarProfile.publisher_avatar_id == db_session_raw.avatar_id)
                .first()
            )
            if avatar_profile and avatar_profile.refined_prompt:
                refined_prompt = avatar_profile.refined_prompt.strip() or None

        # ── Session summary + memories ────────────────────────────────────────
        session_summary = get_recent_session_summary(
            db, session_id, exclude_run_id=session_run_id
        )
        memories: list = []
        if settings.demo_mode:
            # TEMP demo layer: skip DB retrieval, use scripted memory for determinism.
            from app.services import demo_service
            memories = demo_service.get_demo_memories()
        elif db_session_raw:
            memories = get_user_memories(
                db,
                user_id=db_session_raw.user_id,
                avatar_id=db_session_raw.avatar_id,
            )

        # Merge voice from AvatarConfiguration into assistant_parameters so the
        # ephemeral token uses the publisher's chosen voice, not the session default.
        _ap = (
            session_run.assistant_parameters.model_dump()
            if hasattr(session_run.assistant_parameters, "model_dump")
            else dict(session_run.assistant_parameters or {})
        )

        # ── Knowledge context: avatar docs + course materials ─────────────────
        # Collect avatar-level knowledge documents (uploaded under the Knowledge tab)
        # and course-level knowledge chunks (uploaded as course materials) so they
        # are injected into the realtime session's system prompt via rag_context.
        rag_parts: list[str] = []

        if db_session_raw and db_session_raw.avatar_id:
            _avcfg = (
                db.query(AvatarConfiguration)
                .filter(AvatarConfiguration.avatar_id == db_session_raw.avatar_id)
                .first()
            )
            if _avcfg:
                if _avcfg.voice:
                    _ap["voice"] = _avcfg.voice.lower()

                # Avatar knowledge documents — use extracted content_text (populated
                # by the background RAG ingestion task on upload).
                _MAX_CHARS_PER_DOC = 1_200
                for doc in (_avcfg.knowledge_documents or []):
                    if doc.content_text and doc.content_text.strip():
                        excerpt = doc.content_text.strip()[:_MAX_CHARS_PER_DOC]
                        rag_parts.append(f"[Knowledge: {doc.title}]\n{excerpt}")

        # Course material chunks — retrieve from KnowledgeChunk rows scoped to the
        # session's course (course_id FK on the Session model).
        if db_session_raw and db_session_raw.course_id:
            from app.database.models import KnowledgeChunk as _KC
            _course_chunks = (
                db.query(_KC)
                .filter(_KC.course_id == db_session_raw.course_id)
                .order_by(_KC.created_at)
                .limit(20)  # cap to avoid exceeding token budget
                .all()
            )
            for chunk in _course_chunks:
                if chunk.content and chunk.content.strip():
                    rag_parts.append(f"[Course Material]\n{chunk.content.strip()[:800]}")

        rag_context: str | None = "\n\n".join(rag_parts) if rag_parts else None

        # ── Grading feedback (assessment sessions only) ───────────────────────
        # Read submissionId from raw JSONB — Pydantic drops it from session.assistantParameters
        grading_feedback: dict | None = None
        _submission_id_str = (db_session_raw.assistant_parameters or {}).get("submissionId") if db_session_raw else None
        if _submission_id_str:
            from app.database.models.autograder import AutograderSubmission as _AS
            try:
                _sub_uuid = uuid.UUID(_submission_id_str)
                _sub = db.query(_AS).filter(_AS.id == _sub_uuid).first()
                if _sub and _sub.result_json:
                    grading_feedback = _sub.result_json
            except Exception as _ge:
                logger.warning("Could not load grading feedback for session %s: %s", session_id, _ge)

        # ── Resolve prompt via PromptResolutionService ────────────────────────
        # Map session_mode → use_case string then resolve; falls back to None so
        # the legacy template-version path in build_realtime_instructions applies.
        _use_case_map = {
            "teaching": "session.teaching",
            "examination": "session.examination",
            "consultation": "session.conversation",
        }
        _use_case = _use_case_map.get((session_mode or "teaching").lower(), "session.teaching")
        _avatar_id = db_session_raw.avatar_id if db_session_raw else None
        _session_prompt_id = db_session_raw.prompt_template_id if db_session_raw else None
        resolved_system_prompt: str | None = PromptResolutionService().resolve(
            db, _avatar_id, _use_case, prompt_template_id=_session_prompt_id
        )

        token_data = await openai_service.generate_ephemeral_token(
            _ap,
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
            refined_prompt=refined_prompt,
            rag_context=rag_context,
            resolved_system_prompt=resolved_system_prompt,
            grading_feedback=grading_feedback,
        )
        # ── Build avatar display config from variant_snapshot ─────────────────
        snapshot = getattr(session_run, "variant_snapshot", None) or {}
        logger.info(f"🎭 variant_snapshot for run {session_run_id}: {snapshot}")

        model_url = snapshot.get("model_url")
        heygen_id = snapshot.get("heygen_avatar_id")
        variant_name = snapshot.get("name")
        language = snapshot.get("language", "en")

        # Infer render_type — handles old snapshots that predate the render_type field.
        if "render_type" in snapshot:
            render_type = snapshot["render_type"]
        elif snapshot.get("model_3d_id"):
            render_type = "3d"
        elif snapshot.get("heygen_avatar_id"):
            render_type = "heygen"
        else:
            render_type = "static"

        # Fallback: if snapshot is empty / missing 3D info, resolve from the live
        # avatar_variant row (handles session runs created before snapshot was enriched).
        if render_type == "static" and not snapshot:
            _variant_id = getattr(session_run, "avatar_variant_id", None)
            if not _variant_id and db_session_raw and db_session_raw.avatar_id:
                from app.services.avatar_variant_service import resolve_default_variant as _rdv
                _fallback_v = _rdv(db_session_raw.avatar_id, db)
                if _fallback_v:
                    _variant_id = _fallback_v.id
                    variant_name = variant_name or _fallback_v.name
                    language = language or _fallback_v.language or "en"
            if _variant_id:
                from app.database.models.variants import AvatarVariant as _AV
                _v = db.query(_AV).filter(_AV.id == _variant_id).first()
                if _v:
                    variant_name = variant_name or _v.name
                    language = _v.language or language
                    if _v.model_3d_id:
                        render_type = "3d"
                        heygen_id = None
                    elif _v.heygen_avatar_id:
                        render_type = "heygen"
                        heygen_id = _v.heygen_avatar_id

        # Resolve model URL for 3D renders — covers both old snapshots (no model_url)
        # and the live fallback path above.
        if render_type == "3d" and not model_url:
            from app.database.models.variants import AvatarVariant as _AV2, Avatar3DModel as _A3DM
            _model_3d_id = snapshot.get("model_3d_id")
            if not _model_3d_id:
                _vid = getattr(session_run, "avatar_variant_id", None)
                if _vid:
                    _vrow = db.query(_AV2).filter(_AV2.id == _vid).first()
                    if _vrow:
                        _model_3d_id = str(_vrow.model_3d_id) if _vrow.model_3d_id else None
            if _model_3d_id:
                m3d = db.query(_A3DM).filter(_A3DM.id == _model_3d_id).first()
                if m3d:
                    model_url = getattr(m3d, "model_url", None) or getattr(m3d, "file_path", None)

        # ── Final fallback: AvatarConfiguration.additional_settings ──────────
        # The publisher UI stores renderType / glbLibraryId directly in this JSONB
        # column.  When no variant has 3D info, read it from here.
        if render_type == "static" and db_session_raw and db_session_raw.avatar_id:
            _av_cfg = (
                db.query(AvatarConfiguration)
                .filter(AvatarConfiguration.avatar_id == db_session_raw.avatar_id)
                .first()
            )
            if _av_cfg and _av_cfg.additional_settings:
                _as = _av_cfg.additional_settings
                _cfg_render = _as.get("renderType") or _as.get("render_type")
                _cfg_glb = _as.get("glbLibraryId") or _as.get("glb_library_id") or _as.get("modelUrl")
                if _cfg_render == "3d":
                    render_type = "3d"
                    model_url = model_url or _cfg_glb
                elif _cfg_render in ("heygen", "talkingheads"):
                    render_type = _cfg_render
                    heygen_id = heygen_id or _as.get("heygenAvatarId") or _as.get("heygen_avatar_id")
                logger.info(f"🎭 additional_settings fallback → render_type={render_type}, model_url={model_url}")

        logger.info(f"🎭 resolved → render_type={render_type}, model_url={model_url}, variant_name={variant_name}")

        # Avatar image (static fallback) — lives on AvatarTemplate, not Avatar
        avatar_image_url: str | None = None
        if db_session_raw and db_session_raw.avatar_id:
            _av = db.query(Avatar).filter(Avatar.id == db_session_raw.avatar_id).first()
            if _av and _av.template_id:
                _tmpl = db.query(AvatarTemplate).filter(AvatarTemplate.id == _av.template_id).first()
                if _tmpl:
                    avatar_image_url = _tmpl.avatar_image_path
            if not avatar_image_url and _av:
                avatar_image_url = getattr(_av, "avatar_image_path", None)

        return EphemeralTokenResponse(
            client_secret=token_data["client_secret"],
            realtime_model=token_data.get("model"),
            avatar_render_type=render_type,
            avatar_name=variant_name,
            avatar_image_url=avatar_image_url,
            glb_library_id=model_url,
            heygen_avatar_id=heygen_id,
            heygen_quality="high",
            session_language=language,
            session_mode=session_mode,
        )

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
