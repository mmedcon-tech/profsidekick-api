"""
Publisher-only SAE management routes.

POST  /api/sae/publisher/students/batch                   → pre-generate N students + tokens
GET   /api/sae/publisher/students                         → list all students with status
GET   /api/sae/publisher/students/{student_id}            → single student detail + submission
POST  /api/sae/publisher/students/{student_id}/submit     → submit on behalf of a student
PATCH /api/sae/publisher/students/{student_id}/submission → instructor edits to grading result
"""

import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import SAEStudent, SAESubmission, User
from app.dependencies.auth import require_publisher
from app.schemas.sae import (
    SAEBatchCreateRequest,
    SAEBatchCreateResponse,
    SAEStudentDetail,
    SAEStudentRow,
    SAESubmissionEditRequest,
    SAESubmissionResultPublisher,
)
from app.services import sae_service
from app.services.gemini_file_cache import autograder_cache

router = APIRouter(prefix="/api/sae/publisher", tags=["sae-publisher"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_own_student(
    student_id: str,
    publisher: User,
    db: Session,
) -> SAEStudent:
    """Resolve student UUID and verify it belongs to the calling publisher."""
    try:
        sid = uuid.UUID(student_id)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Invalid student_id format.")
    student = db.query(SAEStudent).filter(SAEStudent.id == sid).first()
    if not student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Student not found.")
    if student.publisher_id != publisher.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="You do not own this student.")
    return student


def _student_to_row(student: SAEStudent, db: Session) -> SAEStudentRow:
    inv = student.invitation
    return SAEStudentRow(
        id=student.id,
        student_number=student.student_number,
        student_code=student.student_code,
        display_name=student.display_name,
        invitation_url=sae_service._build_invitation_url(inv.token) if inv else "",
        invitation_token=inv.token if inv else "",
        is_activated=student.is_activated,
        activated_at=student.activated_at,
        has_submitted=student.has_submitted,
        submitted_at=student.submitted_at,
    )


def _sub_to_result_publisher(sub: SAESubmission) -> SAESubmissionResultPublisher:
    """Build the publisher-facing submission result with edit metadata."""
    effective_rj = sae_service.get_effective_result_json(sub)
    return SAESubmissionResultPublisher(
        id=sub.id,
        score=sub.score,
        overall_confidence=sub.overall_confidence,
        review_required=sub.review_required,
        result_json=effective_rj,
        submitted_by_publisher=sub.submitted_by_publisher,
        created_at=sub.created_at,
        is_edited=sub.edited_result_json is not None,
        last_edited_at=sub.last_edited_at,
        handwritten_filename=sub.handwritten_filename,
        webassign_filename=sub.webassign_filename,
    )


def _student_to_detail(student: SAEStudent, db: Session) -> SAEStudentDetail:
    inv = student.invitation
    sub = student.submission
    return SAEStudentDetail(
        id=student.id,
        student_number=student.student_number,
        student_code=student.student_code,
        display_name=student.display_name,
        invitation_url=sae_service._build_invitation_url(inv.token) if inv else "",
        invitation_token=inv.token if inv else "",
        is_activated=student.is_activated,
        activated_at=student.activated_at,
        has_submitted=student.has_submitted,
        submitted_at=student.submitted_at,
        submission=_sub_to_result_publisher(sub) if sub else None,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/students/batch", response_model=SAEBatchCreateResponse)
def create_student_batch(
    body: SAEBatchCreateRequest,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Pre-generate `count` student slots and their one-time invitation links.
    Calling this again adds MORE students to the existing pool (does not replace).
    No emails are sent — the returned invitation_url list is the only delivery channel.
    """
    students = sae_service.create_student_batch(
        db=db,
        publisher_id=publisher.id,
        count=body.count,
        expires_days=body.expires_days,
    )
    rows = [_student_to_row(s, db) for s in students]
    return SAEBatchCreateResponse(students=rows, total_created=len(rows))


@router.get("/students", response_model=list[SAEStudentRow])
def list_students(
    search: Optional[str] = Query(None, description="Filter by code or name"),
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Return all students belonging to this publisher, ordered by student_number.
    Optionally filter by student_code or display_name (case-insensitive).
    """
    students = sae_service.get_publisher_students(
        db=db,
        publisher_id=publisher.id,
        search=search,
    )
    return [_student_to_row(s, db) for s in students]


@router.get("/students/{student_id}", response_model=SAEStudentDetail)
def get_student(
    student_id: str,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """Return a single student with their submission details (if any)."""
    student = _require_own_student(student_id, publisher, db)
    return _student_to_detail(student, db)


@router.post("/students/{student_id}/submit", response_model=SAESubmissionResultPublisher)
async def submit_on_behalf(
    student_id: str,
    student_answer: UploadFile = File(..., description="Handwritten exam PDF"),
    webassign_pdf: UploadFile = File(..., description="WebAssign questions PDF"),
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Submit on behalf of a student who has not yet submitted.
    Blocked if the student has already submitted (409 Conflict).
    Runs the same LLM grading pipeline as the Math autograder.
    """
    if not autograder_cache.loaded:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Autograder not ready. Check server startup logs.",
        )

    student = _require_own_student(student_id, publisher, db)

    if student.has_submitted:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This student has already submitted. Publisher cannot override an existing submission.",
        )

    handwritten_bytes = await student_answer.read()
    webassign_bytes = await webassign_pdf.read()

    submission = await sae_service.grade_and_save_submission(
        db=db,
        student=student,
        handwritten_bytes=handwritten_bytes,
        handwritten_filename=student_answer.filename or "handwritten.pdf",
        webassign_bytes=webassign_bytes,
        webassign_filename=webassign_pdf.filename or "webassign.pdf",
        submitted_by_publisher=True,
        publisher_user_id=publisher.id,
    )
    return _sub_to_result_publisher(submission)


@router.patch("/students/{student_id}/submission", response_model=SAESubmissionResultPublisher)
def edit_submission(
    student_id: str,
    body: SAESubmissionEditRequest,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Instructor edits to a grading result.

    Only overall_feedback and per-question score/feedback are editable.
    The original LLM output (result_json) is preserved; edits are stored
    separately in edited_result_json and become the canonical grade shown
    to both publisher and student.
    Recalculates the total score from the updated per-question scores.
    """
    student = _require_own_student(student_id, publisher, db)

    if not student.submission:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="This student has no submission to edit.",
        )

    question_edits = (
        [{"id": qe.id, "score": qe.score, "feedback": qe.feedback}
         for qe in body.questions]
        if body.questions else []
    )

    updated = sae_service.update_submission_edit(
        db=db,
        submission=student.submission,
        overall_feedback=body.overall_feedback,
        question_edits=question_edits,
        editor_id=publisher.id,
    )
    return _sub_to_result_publisher(updated)


@router.get("/students/{student_id}/files/{file_type}")
def get_student_file(
    student_id: str,
    file_type: Literal["handwritten", "webassign"],
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Stream a student's submitted PDF to the publisher.
    Ownership is verified — publishers can only access their own students' files.
    """
    student = _require_own_student(student_id, publisher, db)
    sub = student.submission
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No submission found for this student.")

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
