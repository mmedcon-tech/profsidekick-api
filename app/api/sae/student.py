"""
Student-facing SAE routes.

All endpoints require the caller to be an activated SAE student
(verified by the require_sae_subscriber dependency below).

GET  /api/sae/student/me          → own SAE student profile
GET  /api/sae/student/submission  → own submission (404 if not yet submitted)
POST /api/sae/student/submit      → one-time file upload + grading
"""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import SAEStudent, User
from app.dependencies.auth import require_subscriber
from app.schemas.sae import SAEStudentMe, SAESubmissionResult
from app.services import sae_service
from app.services.gemini_file_cache import autograder_cache

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
        country_of_origin=sae_student.country_of_origin,
        curriculum=sae_student.curriculum,
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
        overall_confidence=sub.overall_confidence,
        review_required=sub.review_required,
        result_json=sae_service.get_effective_result_json(sub),
        submitted_by_publisher=sub.submitted_by_publisher,
        created_at=sub.created_at,
        handwritten_filename=sub.handwritten_filename,
        webassign_filename=sub.webassign_filename,
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
        overall_confidence=submission.overall_confidence,
        review_required=submission.review_required,
        result_json=sae_service.get_effective_result_json(submission),
        submitted_by_publisher=submission.submitted_by_publisher,
        created_at=submission.created_at,
        handwritten_filename=submission.handwritten_filename,
        webassign_filename=submission.webassign_filename,
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

    disk_path = Path(file_path)
    if not disk_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found on server.")

    return FileResponse(
        path=str(disk_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
