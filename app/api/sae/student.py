"""
Student-facing SAE routes.

Submit access: only users with an activated SAEStudent row for the target assessment.
Raises 403 for regular subscribers or wrong assessment_id.

GET  /api/sae/student/me                              → enrolment state + triggers sync
GET  /api/sae/student/enrollments                     → all active enrolments (triggers sync)
GET  /api/sae/student/submissions                     → all submissions; optional ?assessment_id
GET  /api/sae/student/submissions/{id}                → single historical submission (any enrolment)
GET  /api/sae/student/submissions/{id}/files/{type}   → PDF for a historical submission
POST /api/sae/student/submit                          → file upload + grading; requires assessment_id form field

COMMENTED OUT (legacy, no frontend callers):
  GET /api/sae/student/submission     → superseded by /submissions
  GET /api/sae/student/files/{type}   → superseded by /submissions/{id}/files/{type}
"""

import uuid as _uuid
import os
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import SAEAssessment, SAEStudent, SAESubmission, User
from app.dependencies.auth import require_subscriber
from app.schemas.sae import SAEStudentEnrollment, SAEStudentMe, SAESubmissionResult
from app.services import sae_service
from app.services.gemini_file_cache import autograder_cache
from app.services.r2_service import r2

router = APIRouter(prefix="/api/sae/student", tags=["sae-student"])


# ── Auth dependencies ──────────────────────────────────────────────────────────

# No active callers — only used by legacy endpoints below. Commented out, not deleted.
# async def get_optional_sae_student(
#     current_user: User = Depends(require_subscriber),
#     db: Session = Depends(get_db),
# ) -> Optional[SAEStudent]:
#     """
#     Require a valid subscriber JWT, then resolve the caller's first SAEStudent row.
#     Returns None when the user is a regular subscriber not enrolled in the SAE.
#     Used by legacy single-assessment endpoints (submission, files).
#     """
#     return (
#         db.query(SAEStudent)
#         .filter(SAEStudent.user_id == current_user.id)
#         .first()
#     )


# ── Sync helper ────────────────────────────────────────────────────────────────

def _sync_enrollments(db: Session, user_id: _uuid.UUID) -> None:
    """
    Ensure the user has SAEStudent rows for every active assessment across all
    publishers they have access to. Commits if any rows were created.
    Called on /me and /enrollments so new assessments auto-appear on dashboard load.
    """
    publisher_ids = (
        db.query(SAEStudent.publisher_id)
        .filter(SAEStudent.user_id == user_id)
        .distinct()
        .all()
    )
    for (pid,) in publisher_ids:
        sae_service.ensure_student_access(db, user_id, pid)
    if publisher_ids:
        db.commit()


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


def _stream_file(file_path: str, filename: str) -> Response:
    """Serve a PDF from R2 or local disk."""
    if r2.enabled and not os.path.isabs(file_path):
        try:
            data = r2.download(file_path)
        except RuntimeError as exc:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve file from storage: {exc}",
            )
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    disk_path = Path(file_path)
    if not disk_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found on server.")
    try:
        data = disk_path.read_bytes()
    except OSError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read file: {exc}",
        )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/me", response_model=SAEStudentMe)
def get_my_profile(
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """
    Return the SAE enrolment state for the currently authenticated user.
    Triggers a background sync so any new active assessments auto-appear.
    Returns the first enrolment for backward compatibility; use /enrollments for the full list.
    Regular subscribers who are not in the SAE system receive is_enrolled=False.
    """
    _sync_enrollments(db, current_user.id)

    sae_student = db.query(SAEStudent).filter(SAEStudent.user_id == current_user.id).first()
    if not sae_student:
        return SAEStudentMe(is_enrolled=False)

    assessment = db.query(SAEAssessment).filter(
        SAEAssessment.id == sae_student.assessment_id
    ).first()
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
        assessment_id=sae_student.assessment_id,
        assessment_name=assessment.name if assessment else None,
    )


@router.get("/enrollments", response_model=list[SAEStudentEnrollment])
def get_my_enrollments(
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """
    Return all active SAE enrolments for the authenticated student.
    Triggers a sync so any new active assessments auto-appear without requiring
    the student to re-use their invitation link.
    Returns an empty list for regular subscribers not enrolled in any assessment.
    """
    _sync_enrollments(db, current_user.id)

    students = (
        db.query(SAEStudent)
        .filter(
            SAEStudent.user_id == current_user.id,
            SAEStudent.is_activated == True,  # noqa: E712
        )
        .order_by(SAEStudent.created_at.asc())
        .all()
    )

    result: list[SAEStudentEnrollment] = []
    for s in students:
        assessment = db.query(SAEAssessment).filter(
            SAEAssessment.id == s.assessment_id
        ).first()
        result.append(SAEStudentEnrollment(
            id=s.id,
            student_number=s.student_number,
            student_code=s.student_code,
            display_name=s.display_name,
            is_activated=s.is_activated,
            submission_count=s.submission_count,
            country_of_origin=s.country_of_origin,
            curriculum=s.curriculum,
            assessment_id=s.assessment_id,
            assessment_name=assessment.name if assessment else None,
        ))
    return result


# Legacy endpoint — no frontend callers. GET /submissions is the active replacement.
# Commented out, not deleted.
# @router.get("/submission", response_model=SAESubmissionResult)
# def get_my_submission(
#     sae_student: Optional[SAEStudent] = Depends(get_optional_sae_student),
# ):
#     sub = sae_student.submission if sae_student else None
#     if not sub:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="You have not submitted yet.",
#         )
#     return _sub_to_result(sub)


@router.get("/submissions", response_model=list[SAESubmissionResult])
def list_my_submissions(
    assessment_id: Optional[str] = None,
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """
    Return all submissions for the authenticated student, ordered oldest-first.
    Pass ?assessment_id=<uuid> to scope to a specific assessment.
    Without the param, returns submissions for the student's first enrolled assessment.
    Returns an empty list for regular subscribers or students who have not submitted.
    """
    q = db.query(SAEStudent).filter(SAEStudent.user_id == current_user.id)
    if assessment_id:
        q = q.filter(SAEStudent.assessment_id == assessment_id)
    sae_student = q.first()
    if not sae_student:
        return []
    return [_sub_to_result(sub) for sub in sae_service.get_student_submissions(db, sae_student)]


@router.get("/submissions/{submission_id}", response_model=SAESubmissionResult)
def get_my_submission_by_id(
    submission_id: str,
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """
    Return a single historical submission by ID.
    Searches across all of the student's enrolments so assessment_id is not needed.
    Returns 404 for non-enrolled callers or unknown/unowned submission IDs.
    """
    try:
        sub_uuid = _uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid submission ID.")

    sub = (
        db.query(SAESubmission)
        .join(SAEStudent, SAESubmission.student_id == SAEStudent.id)
        .filter(
            SAESubmission.id == sub_uuid,
            SAEStudent.user_id == current_user.id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Submission not found.")
    return _sub_to_result(sub)


@router.get("/submissions/{submission_id}/files/{file_type}")
def get_my_submission_file(
    submission_id: str,
    file_type: Literal["handwritten", "webassign"],
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """
    Stream a PDF from a specific historical submission.
    Searches across all of the student's enrolments — assessment_id not needed.
    Returns 404 for non-enrolled callers or unknown/unowned submission IDs.
    """
    try:
        sub_uuid = _uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid submission ID.")

    sub = (
        db.query(SAESubmission)
        .join(SAEStudent, SAESubmission.student_id == SAEStudent.id)
        .filter(
            SAESubmission.id == sub_uuid,
            SAEStudent.user_id == current_user.id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Submission not found.")

    file_path = sub.handwritten_file_path if file_type == "handwritten" else sub.webassign_file_path
    filename = (
        sub.handwritten_filename if file_type == "handwritten" else sub.webassign_filename
    ) or f"{file_type}.pdf"

    if not file_path:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="File path not recorded for this submission.",
        )
    return _stream_file(file_path, filename)


@router.post("/submit", response_model=SAESubmissionResult)
async def submit(
    student_answer: UploadFile = File(..., description="Handwritten exam PDF"),
    webassign_pdf: UploadFile = File(..., description="WebAssign questions PDF"),
    assessment_id: Optional[str] = Form(None, description="UUID of the assessment to submit to"),
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """
    Exam submission. Requires SAE enrolment (403 otherwise).
    Pass assessment_id as a form field to target a specific assessment; if omitted and
    the student has exactly one enrolment, that assessment is used automatically.
    Returns 409 if the student has reached the 5-submission limit.
    """
    if not autograder_cache.loaded:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Autograder not ready. Check server startup logs.",
        )

    q = db.query(SAEStudent).filter(
        SAEStudent.user_id == current_user.id,
        SAEStudent.is_activated == True,  # noqa: E712
    )
    if assessment_id:
        q = q.filter(SAEStudent.assessment_id == assessment_id)

    sae_student = q.first()
    if not sae_student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this assessment.",
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


# Legacy endpoint — no frontend callers. GET /submissions/{id}/files/{type} is the active replacement.
# Commented out, not deleted.
# @router.get("/files/{file_type}")
# def get_my_file(
#     file_type: Literal["handwritten", "webassign"],
#     sae_student: Optional[SAEStudent] = Depends(get_optional_sae_student),
# ):
#     sub = sae_student.submission if sae_student else None
#     if not sub:
#         raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No submission found.")
#     file_path = sub.handwritten_file_path if file_type == "handwritten" else sub.webassign_file_path
#     filename = (
#         sub.handwritten_filename if file_type == "handwritten" else sub.webassign_filename
#     ) or f"{file_type}.pdf"
#     if not file_path:
#         raise HTTPException(
#             status.HTTP_404_NOT_FOUND,
#             detail="File path not recorded for this submission.",
#         )
#     return _stream_file(file_path, filename)
