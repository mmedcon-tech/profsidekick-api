"""
Student-facing SAE routes.

All endpoints require the caller to be an activated SAE student
(verified by the require_sae_subscriber dependency below).

GET  /api/sae/student/me          → own SAE student profile
GET  /api/sae/student/submission  → own submission (404 if not yet submitted)
POST /api/sae/student/submit      → one-time file upload + grading
"""

import os
from pathlib import Path
from typing import Literal
import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import SAEQuestionComment, SAEStudent, User
from app.dependencies.auth import require_subscriber
from app.schemas.sae import SAEStudentMe, SAESubmissionResult
from app.schemas.sae import (SAEQuestionCommentRequest, SAEQuestionCommentResponse, SAEStudentMe, SAESubmissionResult,)
from app.services import sae_service
from app.services.gemini_file_cache import autograder_cache
from app.services.r2_service import r2
from app.services.sae_transcription_service import (SAE_TRANSCRIPTION_MODEL, transcribe_sae_handwritten,)

router = APIRouter(prefix="/api/sae/student", tags=["sae-student"])

# ── SAE-specific auth dependency ───────────────────────────────────────────────

async def require_sae_subscriber(
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
) -> SAEStudent:
    """
    Resolve the calling user as an activated SAE student.
    Raises 403 if the user exists but is not in sae_students —
    this prevents regular subscribers from accessing SAE-only routes.
    """
    sae_student = (
        db.query(SAEStudent)
        .filter(SAEStudent.user_id == current_user.id)
        .first()
    )
    if not sae_student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not registered for the Self Assessment Exam.",
        )
    return sae_student

def _comment_responses(submission) -> list[SAEQuestionCommentResponse]:
    return [
        SAEQuestionCommentResponse(
            id=comment.id,
            question_id=comment.question_id,
            comment=comment.comment,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
        )
        for comment in submission.comments
    ]
# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/me", response_model=SAEStudentMe)
def get_my_profile(
    sae_student: SAEStudent = Depends(require_sae_subscriber),
):
    """Return the SAE student profile for the currently authenticated user."""
    return SAEStudentMe(
        id=sae_student.id,
        student_number=sae_student.student_number,
        student_code=sae_student.student_code,
        display_name=sae_student.display_name,
        is_activated=sae_student.is_activated,
        has_submitted=sae_student.has_submitted,
    )


@router.get("/submission", response_model=SAESubmissionResult)
def get_my_submission(
    sae_student: SAEStudent = Depends(require_sae_subscriber),
):
    """Return the student's submission. 404 if they haven't submitted yet."""
    sub = sae_student.submission
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have not submitted yet.",
        )
    return SAESubmissionResult(
        id=sub.id,
        score=sub.score,
        review_required=sub.review_required,
        result_json=sae_service.get_effective_result_json(sub),
        submitted_by_publisher=sub.submitted_by_publisher,
        created_at=sub.created_at,
        handwritten_filename=sub.handwritten_filename,
        webassign_filename=sub.webassign_filename,
        comments=_comment_responses(sub),
    )

@router.post(
    "/submission/comments/{question_id}",
    response_model=SAEQuestionCommentResponse,)
def submit_question_comment(
    question_id: str,
    body: SAEQuestionCommentRequest,
    sae_student: SAEStudent = Depends(require_sae_subscriber),
    db: Session = Depends(get_db),):
    """
    Create or update the authenticated student's comment for one question.
    Only one comment is stored per submission and question.
    """
    submission = sae_student.submission

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have not submitted an exam yet.",
        )

    normalized_question_id = question_id.strip()
    comment_text = body.comment.strip()

    if not normalized_question_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Question ID cannot be empty.",
        )

    effective_result = sae_service.get_effective_result_json(submission) or {}
    questions = effective_result.get("questions", [])

    question_exists = any(
        str(question.get("id")) == normalized_question_id
        for question in questions
        if isinstance(question, dict)
    )

    if not question_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found in this submission.",
        )

    existing_comment = (
        db.query(SAEQuestionComment)
        .filter(
            SAEQuestionComment.submission_id == submission.id,
            SAEQuestionComment.question_id == normalized_question_id,
        )
        .first()
    )

    if existing_comment:
        existing_comment.comment = comment_text
        saved_comment = existing_comment
    else:
        saved_comment = SAEQuestionComment(
            submission_id=submission.id,
            question_id=normalized_question_id,
            comment=comment_text,
        )
        db.add(saved_comment)

    db.commit()
    db.refresh(saved_comment)

    return SAEQuestionCommentResponse(
        id=saved_comment.id,
        question_id=saved_comment.question_id,
        comment=saved_comment.comment,
        created_at=saved_comment.created_at,
        updated_at=saved_comment.updated_at,
    )

@router.post("/transcribe")
async def transcribe_submission(
    student_answer: UploadFile = File(..., description="Handwritten exam PDF"),
    webassign_pdf: UploadFile = File(..., description="WebAssign questions PDF"),
    sae_student: SAEStudent = Depends(require_sae_subscriber),
):
    """
    First step of the official SAE submission pipeline.

    Saves the student's handwritten PDF and WebAssign PDF to durable storage,
    creates the handwritten transcript using both PDFs, and saves the transcript.
    Grading happens in the subsequent /grade-draft request.
    """
    if sae_student.has_submitted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted. Only one submission is allowed.",
        )

    handwritten_bytes = await student_answer.read()
    webassign_bytes = await webassign_pdf.read()

    if not handwritten_bytes or not webassign_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both uploaded PDFs must contain data.",
        )

    handwritten_filename = student_answer.filename or "handwritten.pdf"
    webassign_filename = webassign_pdf.filename or "webassign.pdf"

    metadata = {
        "handwritten_filename": handwritten_filename,
        "webassign_filename": webassign_filename,
        "transcript_model": SAE_TRANSCRIPTION_MODEL,
    }
    metadata_bytes = json.dumps(metadata).encode("utf-8")

    handwritten_key = sae_service.build_submission_storage_key(
        sae_student.student_code,
        "handwritten.pdf",
    )
    webassign_key = sae_service.build_submission_storage_key(
        sae_student.student_code,
        "webassign.pdf",
    )
    metadata_key = sae_service.build_submission_storage_key(
        sae_student.student_code,
        "metadata.json",
    )
    transcript_key = sae_service.build_submission_storage_key(
        sae_student.student_code,
        "handwritten_transcript.md",
    )

    try:
        if r2.enabled:
            r2.upload(
                handwritten_key,
                handwritten_bytes,
                content_type="application/pdf",
            )
            r2.upload(
                webassign_key,
                webassign_bytes,
                content_type="application/pdf",
            )
            r2.upload(
                metadata_key,
                metadata_bytes,
                content_type="application/json",
            )
        else:
            submission_dir = sae_service.build_submission_dir(
                sae_student.student_code
            )

            (submission_dir / "handwritten.pdf").write_bytes(
                handwritten_bytes
            )
            (submission_dir / "webassign.pdf").write_bytes(
                webassign_bytes
            )
            (submission_dir / "metadata.json").write_bytes(
                metadata_bytes
            )

        handwritten_transcript = await transcribe_sae_handwritten(
            handwritten_bytes=handwritten_bytes,
            webassign_bytes=webassign_bytes,
        )

        transcript_text = handwritten_transcript["latex"]

        if r2.enabled:
            r2.upload(
                transcript_key,
                transcript_text.encode("utf-8"),
                content_type="text/markdown; charset=utf-8",
            )
        else:
            submission_dir = sae_service.build_submission_dir(
                sae_student.student_code
            )
            (
                submission_dir / "handwritten_transcript.md"
            ).write_text(
                transcript_text,
                encoding="utf-8",
            )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Transcription failed: {exc}",
        )

    return {
        "student_code": sae_student.student_code,
        "display_name": sae_student.display_name,
        "transcription_complete": True,
        "transcript": {
            "handwritten": handwritten_transcript,
        },
    }


@router.post("/grade-draft", response_model=SAESubmissionResult)
async def grade_draft_submission(
    sae_student: SAEStudent = Depends(require_sae_subscriber),
    db: Session = Depends(get_db),
):
    """
    Second step of the official SAE submission pipeline.

    Loads the already-saved handwritten PDF, WebAssign PDF, metadata, and
    handwritten transcript from durable storage, then sends them for grading.
    """
    if not autograder_cache.loaded:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Autograder not ready. Check server startup logs.",
        )

    if sae_student.has_submitted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted. Only one submission is allowed.",
        )

    handwritten_key = sae_service.build_submission_storage_key(
        sae_student.student_code,
        "handwritten.pdf",
    )
    webassign_key = sae_service.build_submission_storage_key(
        sae_student.student_code,
        "webassign.pdf",
    )
    metadata_key = sae_service.build_submission_storage_key(
        sae_student.student_code,
        "metadata.json",
    )
    transcript_key = sae_service.build_submission_storage_key(
        sae_student.student_code,
        "handwritten_transcript.md",
    )

    try:
        if r2.enabled:
            handwritten_bytes = r2.download(handwritten_key)
            webassign_bytes = r2.download(webassign_key)
            metadata_bytes = r2.download(metadata_key)
            transcript_bytes = r2.download(transcript_key)
            handwritten_stored_path = handwritten_key
            webassign_stored_path = webassign_key
            transcript_stored_path = transcript_key

        else:
            submission_dir = sae_service.build_submission_dir(
                sae_student.student_code
            )

            handwritten_path = submission_dir / "handwritten.pdf"
            webassign_path = submission_dir / "webassign.pdf"
            metadata_path = submission_dir / "metadata.json"
            transcript_path = (
                submission_dir / "handwritten_transcript.md"
            )

            required_paths = [
                handwritten_path,
                webassign_path,
                metadata_path,
                transcript_path,
            ]

            if not all(path.exists() for path in required_paths):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=(
                        "Saved submission files are incomplete. "
                        "Please upload again."
                    ),
                )

            handwritten_bytes = handwritten_path.read_bytes()
            webassign_bytes = webassign_path.read_bytes()
            metadata_bytes = metadata_path.read_bytes()
            transcript_bytes = transcript_path.read_bytes()
            handwritten_stored_path = str(handwritten_path)
            webassign_stored_path = str(webassign_path)
            transcript_stored_path = str(transcript_path)

        metadata = json.loads(metadata_bytes.decode("utf-8"))
        handwritten_transcript = transcript_bytes.decode("utf-8").strip()

        if not handwritten_transcript:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The saved handwritten transcript is empty.",
            )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved submission files could not be loaded: {exc}",
        )

    submission = await sae_service.grade_and_save_submission(
        db=db,
        student=sae_student,
        handwritten_bytes=handwritten_bytes,
        handwritten_filename=metadata.get(
            "handwritten_filename",
            "handwritten.pdf",
        ),
        webassign_bytes=webassign_bytes,
        webassign_filename=metadata.get(
            "webassign_filename",
            "webassign.pdf",
        ),
        submitted_by_publisher=False,
        publisher_user_id=None,
        handwritten_transcript=handwritten_transcript,
        handwritten_file_path=handwritten_stored_path,
        webassign_file_path=webassign_stored_path,
        handwritten_transcript_file_path=transcript_stored_path,
    )
    return SAESubmissionResult(
        id=submission.id,
        score=submission.score,
        review_required=submission.review_required,
        result_json=sae_service.get_effective_result_json(submission),
        submitted_by_publisher=submission.submitted_by_publisher,
        created_at=submission.created_at,
        handwritten_filename=submission.handwritten_filename,
        webassign_filename=submission.webassign_filename,
        comments=_comment_responses(submission),
    )

@router.post("/submit", response_model=SAESubmissionResult)
async def submit(
    student_answer: UploadFile = File(..., description="Handwritten exam PDF"),
    webassign_pdf: UploadFile = File(..., description="WebAssign questions PDF"),
    sae_student: SAEStudent = Depends(require_sae_subscriber),
    db: Session = Depends(get_db),
):
    """
    One-time exam submission. Returns 409 if the student has already submitted.

    Files are stored at uploads/sae/{student_code}/ and graded using the same
    LLM fallback chain as the Math Placement autograder.
    """
    if not autograder_cache.loaded:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Autograder not ready. Check server startup logs.",
        )

    if sae_student.has_submitted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted. Only one submission is allowed.",
        )

    handwritten_bytes = await student_answer.read()
    webassign_bytes = await webassign_pdf.read()

    submission = await sae_service.grade_and_save_submission(
        db=db,
        student=sae_student,
        handwritten_bytes=handwritten_bytes,
        handwritten_filename=student_answer.filename or "handwritten.pdf",
        webassign_bytes=webassign_bytes,
        webassign_filename=webassign_pdf.filename or "webassign.pdf",
        submitted_by_publisher=False,
        publisher_user_id=None,
    )
    return SAESubmissionResult(
        id=submission.id,
        score=submission.score,
        review_required=submission.review_required,
        result_json=sae_service.get_effective_result_json(submission),
        submitted_by_publisher=submission.submitted_by_publisher,
        created_at=submission.created_at,
        handwritten_filename=submission.handwritten_filename,
        webassign_filename=submission.webassign_filename,
        comments=_comment_responses(submission),
    )


@router.get("/files/{file_type}")
def get_my_file(
    file_type: Literal["handwritten", "webassign"],
    sae_student: SAEStudent = Depends(require_sae_subscriber),
):
    """
    Stream the student's own submitted PDF.
    Students can only access their own submission files.
    """
    sub = sae_student.submission
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No submission found.")

    if file_type == "handwritten":
        file_path = sub.handwritten_file_path
        filename = sub.handwritten_filename or "handwritten.pdf"
    else:
        file_path = sub.webassign_file_path
        filename = sub.webassign_filename or "webassign.pdf"

    if not file_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File path not recorded for this submission.")

    if r2.enabled and not os.path.isabs(file_path):
        data = r2.download(file_path)
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    disk_path = Path(file_path)
    if not disk_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found on server.")

    return FileResponse(
        path=str(disk_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
