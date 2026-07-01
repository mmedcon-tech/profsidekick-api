"""
Student-facing SAE routes.

Access is split into two levels:
  - View access  (get_optional_sae_student): any authenticated subscriber.
    Returns None when the caller has no SAE enrolment — endpoints handle gracefully.
  - Submit access (require_sae_submit_access): only users linked to an SAEStudent row.
    Raises 403 for regular subscribers.

GET  /api/sae/student/me                              → enrolment state + profile
GET  /api/sae/student/submission                      → active submission (legacy single)
GET  /api/sae/student/submissions                     → all submissions, oldest first
GET  /api/sae/student/submissions/{id}                → single historical submission
GET  /api/sae/student/submissions/{id}/files/{type}   → PDF for a historical submission
POST /api/sae/student/submit                          → file upload + grading (enrolment required)
GET  /api/sae/student/files/{type}                   → active submission PDF (legacy)
"""

import uuid as _uuid
import os
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import SAEStudent, User
from app.dependencies.auth import require_subscriber
from app.schemas.sae import SAEStudentMe, SAESubmissionResult
from app.services import sae_service
from app.services.gemini_file_cache import autograder_cache
from app.services.r2_service import r2

router = APIRouter(prefix="/api/sae/student", tags=["sae-student"])


# ── Auth dependencies ──────────────────────────────────────────────────────────

async def get_optional_sae_student(
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
) -> Optional[SAEStudent]:
    """
    Require a valid subscriber JWT, then resolve the caller's SAEStudent row.
    Returns None when the user is a regular subscriber not enrolled in the SAE.
    Never raises on missing enrolment — callers decide how to handle that case.
    """
    return (
        db.query(SAEStudent)
        .filter(SAEStudent.user_id == current_user.id)
        .first()
    )


async def require_sae_submit_access(
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
) -> SAEStudent:
    """
    Require the caller to be an enrolled SAE student.
    Raises 403 for regular subscribers who have not been invited.
    Used exclusively on the submit endpoint.
    """
    sae_student = (
        db.query(SAEStudent)
        .filter(SAEStudent.user_id == current_user.id)
        .first()
    )
    if not sae_student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have enough credits.",
        )
    return sae_student


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sub_to_result(sub: "SAESubmission") -> SAESubmissionResult:  # type: ignore[name-defined]
    return SAESubmissionResult(
        id=sub.id,
        submission_number=sub.submission_number,
        is_active=sub.is_active,
        score=sub.score,
        overall_confidence=sub.overall_confidence,
        review_required=sub.review_required,
        result_json=sae_service.get_effective_result_json(sub),
        submitted_by_publisher=sub.submitted_by_publisher,
        created_at=sub.created_at,
        handwritten_filename=sub.handwritten_filename,
        webassign_filename=sub.webassign_filename,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/me", response_model=SAEStudentMe)
def get_my_profile(
    sae_student: Optional[SAEStudent] = Depends(get_optional_sae_student),
):
    """
    Return the SAE enrolment state for the currently authenticated user.
    Regular subscribers who are not in the SAE system receive is_enrolled=False;
    all profile fields are None in that case.
    """
    if not sae_student:
        return SAEStudentMe(is_enrolled=False)
    return SAEStudentMe(
        is_enrolled=True,
        id=sae_student.id,
        student_number=sae_student.student_number,
        student_code=sae_student.student_code,
        display_name=sae_student.display_name,
        is_activated=sae_student.is_activated,
        submission_count=sae_student.submission_count,
        country_of_origin=sae_student.country_of_origin,
        curriculum=sae_student.curriculum,
    )


@router.get("/submission", response_model=SAESubmissionResult)
def get_my_submission(
    sae_student: Optional[SAEStudent] = Depends(get_optional_sae_student),
):
    """
    Return the student's active submission.
    Legacy single-submission endpoint — kept for backward compatibility.
    Prefer GET /submissions for new frontend work.
    Returns 404 when not enrolled or not yet submitted.
    """
    sub = sae_student.submission if sae_student else None
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have not submitted yet.",
        )
    return _sub_to_result(sub)


@router.get("/submissions", response_model=list[SAESubmissionResult])
def list_my_submissions(
    sae_student: Optional[SAEStudent] = Depends(get_optional_sae_student),
    db: Session = Depends(get_db),
):
    """
    Return all submissions for the authenticated student, ordered oldest-first.
    Returns an empty list for regular subscribers or students who have not submitted.
    """
    if not sae_student:
        return []
    return [_sub_to_result(sub) for sub in sae_service.get_student_submissions(db, sae_student)]


@router.get("/submissions/{submission_id}", response_model=SAESubmissionResult)
def get_my_submission_by_id(
    submission_id: str,
    sae_student: Optional[SAEStudent] = Depends(get_optional_sae_student),
    db: Session = Depends(get_db),
):
    """
    Return a single historical submission by ID.
    Students can only access their own submissions.
    Returns 404 for non-enrolled callers or unknown/unowned submission IDs.
    """
    if not sae_student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Submission not found.")
    try:
        sub_uuid = _uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid submission ID.")

    sub = sae_service.get_student_submission_by_id(db, sub_uuid, sae_student)
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Submission not found.")
    return _sub_to_result(sub)


@router.get("/submissions/{submission_id}/files/{file_type}")
def get_my_submission_file(
    submission_id: str,
    file_type: Literal["handwritten", "webassign"],
    sae_student: Optional[SAEStudent] = Depends(get_optional_sae_student),
    db: Session = Depends(get_db),
):
    """
    Stream a PDF from a specific historical submission.
    Students can only access their own files.
    Returns 404 for non-enrolled callers or unknown/unowned submission IDs.
    """
    if not sae_student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Submission not found.")
    try:
        sub_uuid = _uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid submission ID.")

    sub = sae_service.get_student_submission_by_id(db, sub_uuid, sae_student)
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Submission not found.")

    file_path = sub.handwritten_file_path if file_type == "handwritten" else sub.webassign_file_path
    filename = (sub.handwritten_filename if file_type == "handwritten" else sub.webassign_filename) or f"{file_type}.pdf"

    if not file_path:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="File path not recorded for this submission.",
        )

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


@router.post("/submit", response_model=SAESubmissionResult)
async def submit(
    student_answer: UploadFile = File(..., description="Handwritten exam PDF"),
    webassign_pdf: UploadFile = File(..., description="WebAssign questions PDF"),
    sae_student: SAEStudent = Depends(require_sae_submit_access),
    db: Session = Depends(get_db),
):
    """
    Exam submission. Requires SAE enrolment (403 otherwise).
    Returns 409 if the student has reached the 5-submission limit.

    Files are stored at uploads/sae/{student_code}/{submission_number}/ and graded
    using the same LLM fallback chain as the Math Placement autograder.
    """
    if not autograder_cache.loaded:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Autograder not ready. Check server startup logs.",
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
    return _sub_to_result(submission)


@router.get("/files/{file_type}")
def get_my_file(
    file_type: Literal["handwritten", "webassign"],
    sae_student: Optional[SAEStudent] = Depends(get_optional_sae_student),
):
    """
    Stream the student's active submission PDF.
    Legacy endpoint targeting the active submission only.
    Prefer GET /submissions/{id}/files/{type} for historical submissions.
    Returns 404 when not enrolled or no submission exists.
    """
    sub = sae_student.submission if sae_student else None
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No submission found.")

    file_path = sub.handwritten_file_path if file_type == "handwritten" else sub.webassign_file_path
    filename = (sub.handwritten_filename if file_type == "handwritten" else sub.webassign_filename) or f"{file_type}.pdf"

    if not file_path:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="File path not recorded for this submission.",
        )

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
