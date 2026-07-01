"""
Publisher-only SAE management routes.

POST  /api/sae/publisher/assessments                      → create a new assessment (optional course link)
GET   /api/sae/publisher/assessments                      → list all assessments for this publisher
POST  /api/sae/publisher/students/batch                   → pre-generate N students under an assessment
GET   /api/sae/publisher/students                         → list students (all or filtered by assessment)
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
from app.database.models import SAEAssessment, SAEInvitationToken, SAEStudent, SAESubmission, User
from app.dependencies.auth import require_publisher
from app.schemas.sae import (
    SAEAssessmentCreate,
    SAEAssessmentRow,
    SAEBatchCreateRequest,
    SAEBatchCreateResponse,
    SAERegenerateResponse,
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


def _get_active_token(student: SAEStudent, db: Session) -> Optional[SAEInvitationToken]:
    """Return the latest unused invitation token for this student, or None."""
    return (
        db.query(SAEInvitationToken)
        .filter(
            SAEInvitationToken.student_id == student.id,
            SAEInvitationToken.is_used == False,  # noqa: E712
        )
        .order_by(SAEInvitationToken.created_at.desc())
        .first()
    )


def _student_to_row(student: SAEStudent, db: Session) -> SAEStudentRow:
    inv = _get_active_token(student, db)
    return SAEStudentRow(
        id=student.id,
        assessment_id=student.assessment_id,
        student_number=student.student_number,
        student_code=student.student_code,
        display_name=student.display_name,
        invitation_url=sae_service._build_invitation_url(inv.token) if inv else "",
        invitation_token=inv.token if inv else "",
        is_activated=student.is_activated,
        activated_at=student.activated_at,
        submission_count=student.submission_count,
        submitted_at=student.submitted_at,
        country_of_origin=student.country_of_origin,
        curriculum=student.curriculum,
    )


def _sub_to_result_publisher(sub: SAESubmission) -> SAESubmissionResultPublisher:
    """Build the publisher-facing submission result with edit metadata."""
    effective_rj = sae_service.get_effective_result_json(sub)
    return SAESubmissionResultPublisher(
        id=sub.id,
        submission_number=sub.submission_number,
        is_active=sub.is_active,
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
    inv = _get_active_token(student, db)
    all_subs = sae_service.get_student_submissions(db, student)
    return SAEStudentDetail(
        id=student.id,
        student_number=student.student_number,
        student_code=student.student_code,
        display_name=student.display_name,
        invitation_url=sae_service._build_invitation_url(inv.token) if inv else "",
        invitation_token=inv.token if inv else "",
        is_activated=student.is_activated,
        activated_at=student.activated_at,
        submitted_at=student.submitted_at,
        submission_count=student.submission_count,
        submissions=[_sub_to_result_publisher(s) for s in all_subs],
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_own_assessment(
    assessment_id: str,
    publisher: User,
    db: Session,
) -> SAEAssessment:
    """Resolve assessment UUID and verify it belongs to the calling publisher."""
    try:
        aid = uuid.UUID(assessment_id)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Invalid assessment_id format.")
    assessment = db.query(SAEAssessment).filter(SAEAssessment.id == aid).first()
    if not assessment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Assessment not found.")
    if assessment.publisher_id != publisher.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="You do not own this assessment.")
    return assessment


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/assessments", response_model=SAEAssessmentRow, status_code=status.HTTP_201_CREATED)
def create_assessment(
    body: SAEAssessmentCreate,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Create a new assessment.
    Optionally pass course_id to link it to an existing course the publisher owns.
    """
    assessment = sae_service.create_assessment(
        db=db,
        publisher_id=publisher.id,
        name=body.name,
        description=body.description,
        course_id=body.course_id,
    )
    return assessment


@router.get("/assessments", response_model=list[SAEAssessmentRow])
def list_assessments(
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """Return all assessments for this publisher, newest first."""
    return sae_service.get_publisher_assessments(db=db, publisher_id=publisher.id)


@router.post("/students/batch", response_model=SAEBatchCreateResponse)
def create_student_batch(
    body: SAEBatchCreateRequest,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Pre-generate `count` student slots under a specific assessment.
    The assessment must belong to the calling publisher.
    Calling this again adds MORE students to the assessment (does not replace).
    No emails are sent — the returned invitation_url list is the only delivery channel.
    """
    _require_own_assessment(str(body.assessment_id), publisher, db)
    students = sae_service.create_student_batch(
        db=db,
        publisher_id=publisher.id,
        assessment_id=body.assessment_id,
        count=body.count,
        expires_days=body.expires_days,
    )
    rows = [_student_to_row(s, db) for s in students]
    return SAEBatchCreateResponse(students=rows, total_created=len(rows))


@router.get("/students", response_model=list[SAEStudentRow])
def list_students(
    assessment_id: Optional[str] = Query(None, description="Filter to a single assessment"),
    search: Optional[str] = Query(None, description="Filter by code or name"),
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Return students belonging to this publisher.
    Pass assessment_id to scope to one cohort; omit to see all students across all assessments.
    Optionally filter by student_code or display_name (case-insensitive).
    """
    parsed_assessment_id = None
    if assessment_id is not None:
        _require_own_assessment(assessment_id, publisher, db)
        try:
            parsed_assessment_id = uuid.UUID(assessment_id)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Invalid assessment_id format.")

    students = sae_service.get_publisher_students(
        db=db,
        publisher_id=publisher.id,
        assessment_id=parsed_assessment_id,
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
    Submit on behalf of a student.
    Returns 409 if the student has reached the 5-submission limit.
    Runs the same LLM grading pipeline as the Math autograder.
    """
    if not autograder_cache.loaded:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Autograder not ready. Check server startup logs.",
        )

    student = _require_own_student(student_id, publisher, db)

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


@router.post("/students/{student_id}/regenerate", response_model=SAERegenerateResponse)
def regenerate_access(
    student_id: str,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Reset a student's login credentials and issue a fresh invitation link.

    The existing User row and any submission data are fully preserved — only the
    username, email, and password on the User row are mangled so the student
    cannot log in until they complete setup again via the new link.

    Allowed for activated students regardless of submission status.
    Blocked if the student has not yet activated (nothing to reset).
    """
    student = _require_own_student(student_id, publisher, db)

    if not student.is_activated:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This student has not activated their account yet. Share the original invitation link.",
        )

    try:
        invitation_url, invitation_token = sae_service.regenerate_student_access(
            db=db,
            student=student,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))

    return SAERegenerateResponse(
        invitation_url=invitation_url,
        invitation_token=invitation_token,
    )


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
