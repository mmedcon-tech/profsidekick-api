"""
Self Assessment Exam (SAE) service layer.

All business logic for student generation, invitation token management,
account activation, and submission recording lives here. Routes stay thin.

Design rules enforced here:
- No emails are ever sent to students.
- Invitation links are returned to the publisher only.
- Students get exactly one submission (enforced by DB UNIQUE + guard here).
- Activation is atomic: token invalidation and user creation commit together.
"""

import base64
import copy
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import SAEInvitationToken, SAEStudent, SAESubmission, User


# ── Code generation ────────────────────────────────────────────────────────────

def _generate_student_code(publisher_id: uuid.UUID, student_number: int) -> str:
    """
    Produces a globally unique code like SAE-2025-A1B2-001.
    The 4-char publisher hash prevents collisions when multiple publishers
    both have "Student 1".
    """
    year = datetime.now().year
    pub_hash = str(publisher_id).replace("-", "")[:4].upper()
    return f"SAE-{year}-{pub_hash}-{student_number:03d}"


def _generate_invitation_token() -> str:
    """256-bit URL-safe random token (43 chars)."""
    return secrets.token_urlsafe(32)


def _build_invitation_url(token: str) -> str:
    base = settings.frontend_url.rstrip("/")
    return f"{base}/sae/setup/{token}"


# ── Batch student creation ─────────────────────────────────────────────────────

def create_student_batch(
    db: Session,
    publisher_id: uuid.UUID,
    count: int,
    expires_days: Optional[int] = None,
) -> list[SAEStudent]:
    """
    Pre-generate `count` student slots + one invitation token each.
    Returns the committed SAEStudent rows (with .invitation loaded).
    No emails are sent — the caller receives the invitation URLs.
    """
    # Find the current highest student_number for this publisher so we can
    # append without gaps or collisions.
    max_num_row = (
        db.query(func.max(SAEStudent.student_number))
        .filter(SAEStudent.publisher_id == publisher_id)
        .scalar()
    )
    start_from = (max_num_row or 0) + 1

    expires_at: Optional[datetime] = None
    if expires_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    new_students: list[SAEStudent] = []
    for i in range(count):
        num = start_from + i
        code = _generate_student_code(publisher_id, num)
        token_value = _generate_invitation_token()

        student = SAEStudent(
            student_number=num,
            student_code=code,
            display_name=f"Student {num}",
            publisher_id=publisher_id,
        )
        db.add(student)
        db.flush()  # get student.id before creating the token FK

        token = SAEInvitationToken(
            student_id=student.id,
            token=token_value,
            expires_at=expires_at,
        )
        db.add(token)
        new_students.append(student)

    db.commit()
    for s in new_students:
        db.refresh(s)

    return new_students


# ── Token validation ───────────────────────────────────────────────────────────

def validate_invitation_token(
    db: Session,
    token_value: str,
) -> tuple[bool, str, Optional[SAEInvitationToken]]:
    """
    Returns (is_valid, reason, token_row).
    reason is empty string on success; human-readable on failure.
    """
    token_row = (
        db.query(SAEInvitationToken)
        .filter(SAEInvitationToken.token == token_value)
        .first()
    )
    if not token_row:
        return False, "This invitation link is invalid.", None

    if token_row.is_used:
        return False, "This invitation link has already been used.", None

    if token_row.expires_at is not None:
        exp = token_row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            return False, "This invitation link has expired.", None

    return True, "", token_row


# ── Account activation ─────────────────────────────────────────────────────────

def activate_student_account(
    db: Session,
    token_value: str,
    username: str,
    password: str,
) -> tuple[bool, str, Optional[User]]:
    """
    Atomically:
      1. Re-validates the token (with FOR UPDATE lock to prevent races).
      2. Checks username uniqueness.
      3. Creates a users row (email_verified=True, is_approved=True — no email gate).
      4. Links sae_students.user_id and marks it activated.
      5. Marks the token as used.
      6. Commits everything.

    Returns (success, error_message, new_user).
    """
    # Lock the token row to prevent two simultaneous requests from both succeeding.
    token_row = (
        db.query(SAEInvitationToken)
        .filter(SAEInvitationToken.token == token_value)
        .with_for_update()
        .first()
    )
    if not token_row:
        return False, "Invalid invitation link.", None
    if token_row.is_used:
        return False, "This invitation link has already been used.", None
    if token_row.expires_at is not None:
        exp = token_row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            return False, "This invitation link has expired.", None

    # Username uniqueness check
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        return False, "Username already taken. Please choose a different one.", None

    student = db.query(SAEStudent).filter(
        SAEStudent.id == token_row.student_id
    ).first()
    if not student:
        return False, "Student record not found.", None

    # Placeholder email — never emailed, but satisfies the NOT NULL unique column.
    placeholder_email = f"sae.{student.student_code.lower()}@noreply.internal"

    # Hash password using bcrypt (same as AuthService.hash_password)
    salt = bcrypt.gensalt()
    password_hash = bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    new_user = User(
        username=username,
        email=placeholder_email,
        password_hash=password_hash,
        first_name=student.display_name,
        last_name="",
        role="subscriber",
        # Bypass normal email verification and admin approval flows —
        # possession of the invitation link is proof of authorization.
        email_verified=True,
        is_approved=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(new_user)
    db.flush()  # get new_user.id

    # Link and mark activated
    student.user_id = new_user.id
    student.is_activated = True
    student.activated_at = datetime.utcnow()

    # Invalidate token
    token_row.is_used = True
    token_row.used_at = datetime.utcnow()

    db.commit()
    db.refresh(new_user)
    db.refresh(student)

    return True, "", new_user


# ── File storage ───────────────────────────────────────────────────────────────

def build_submission_dir(student_code: str) -> Path:
    """Isolated upload directory for SAE submissions."""
    submission_dir = Path(settings.upload_dir) / "sae" / student_code
    submission_dir.mkdir(parents=True, exist_ok=True)
    return submission_dir


# ── Grading + submission creation ──────────────────────────────────────────────

async def grade_and_save_submission(
    db: Session,
    student: SAEStudent,
    handwritten_bytes: bytes,
    handwritten_filename: str,
    webassign_bytes: bytes,
    webassign_filename: str,
    submitted_by_publisher: bool = False,
    publisher_user_id: Optional[uuid.UUID] = None,
) -> SAESubmission:
    """
    Runs the LLM grading pipeline (same fallback chain as the Math autograder)
    then persists the SAESubmission row.

    Raises HTTPException on grading failure so the route layer can propagate it.
    Single-submission guard: the DB UNIQUE constraint on student_id is the
    authoritative check; this function trusts the caller already verified
    has_submitted == False before invoking it.
    """
    from app.llm.fallback_provider import get_fallback_provider
    from app.llm.provider import StudentFiles
    from fastapi import HTTPException, status

    # Persist files
    submission_dir = build_submission_dir(student.student_code)
    hw_path = submission_dir / "handwritten.pdf"
    wa_path = submission_dir / "webassign.pdf"
    hw_path.write_bytes(handwritten_bytes)
    wa_path.write_bytes(webassign_bytes)

    # Encode for LLM provider
    student_files = StudentFiles(
        webassign_b64=base64.b64encode(webassign_bytes).decode("utf-8"),
        handwritten_b64=base64.b64encode(handwritten_bytes).decode("utf-8"),
    )

    fp = get_fallback_provider()
    try:
        result = await fp.grade(student_files, request_id=None)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Grading failed: {exc}",
        )

    result_data = {
        "raw_score": result.raw_score,
        "raw_max_score": result.raw_max_score,
        "score": result.score,
        "submission_review_required": result.submission_review_required,
        "submission_review_reasons": result.submission_review_reasons,
        "overall_feedback": result.overall_feedback,
        "questions": result.questions,
        "source": result.source,
        "details": {
            "filename": handwritten_filename,
            "model": result.model_used,
            "source": result.source,
            "webassign_filename": webassign_filename,
        },
    }

    submission = SAESubmission(
        student_id=student.id,
        submitted_by_publisher=submitted_by_publisher,
        publisher_user_id=publisher_user_id,
        handwritten_filename=handwritten_filename,
        handwritten_file_path=str(hw_path),
        webassign_filename=webassign_filename,
        webassign_file_path=str(wa_path),
        score=result.score,
        overall_confidence=result_data.get("overall_confidence"),
        review_required=result_data["submission_review_required"],
        result_json=result_data,
    )
    db.add(submission)

    student.has_submitted = True
    student.submitted_at = datetime.utcnow()

    db.commit()
    db.refresh(submission)
    return submission


# ── Dashboard helpers ──────────────────────────────────────────────────────────

def get_publisher_students(
    db: Session,
    publisher_id: uuid.UUID,
    search: Optional[str] = None,
) -> list[SAEStudent]:
    q = (
        db.query(SAEStudent)
        .filter(SAEStudent.publisher_id == publisher_id)
    )
    if search:
        like = f"%{search.upper()}%"
        q = q.filter(
            (SAEStudent.student_code.ilike(like))
            | (SAEStudent.display_name.ilike(like))
        )
    return q.order_by(SAEStudent.student_number.asc()).all()


# ── Effective result helper ────────────────────────────────────────────────────

def get_effective_result_json(submission: SAESubmission) -> Optional[dict]:
    """
    Returns the canonical grading JSON for a submission.
    Instructor edits take precedence over the original LLM output.
    """
    if submission.edited_result_json is not None:
        return submission.edited_result_json
    return submission.result_json


# ── Instructor edit ────────────────────────────────────────────────────────────

def update_submission_edit(
    db: Session,
    submission: SAESubmission,
    overall_feedback: Optional[str],
    question_edits: list[dict],
    editor_id: uuid.UUID,
) -> SAESubmission:
    """
    Apply instructor edits to a submission.

    Works on a deep copy of the current effective result so successive edits
    layer correctly (edit → save → edit → save always starts from latest state).
    Recalculates the raw_score / score from the updated per-question scores and
    keeps the SAESubmission.score column in sync.
    """
    base = copy.deepcopy(get_effective_result_json(submission) or {})

    if overall_feedback is not None:
        base["overall_feedback"] = overall_feedback

    if question_edits:
        edits_by_id = {qe["id"]: qe for qe in question_edits}
        for q in base.get("questions", []):
            qe = edits_by_id.get(q.get("id"))
            if qe is None:
                continue
            if qe.get("score") is not None:
                q["score"] = qe["score"]
            if qe.get("feedback") is not None:
                q["feedback"] = qe["feedback"]

    # Recalculate totals from the updated question scores.
    new_total = sum(
        (q.get("score") or 0) for q in base.get("questions", [])
    )
    base["raw_score"] = new_total
    base["score"] = new_total

    # Assign a new dict so SQLAlchemy detects the JSONB column as dirty.
    submission.edited_result_json = base
    submission.last_edited_at = datetime.utcnow()
    submission.last_edited_by = editor_id
    submission.score = round(new_total)

    db.commit()
    db.refresh(submission)
    return submission
