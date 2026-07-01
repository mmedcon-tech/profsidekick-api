"""
Self Assessment Exam (SAE) service layer.

All business logic for student generation, invitation token management,
account activation, and submission recording lives here. Routes stay thin.

Design rules enforced here:
- No emails are ever sent to students.
- Invitation links are returned to the publisher only.
- Students may submit up to MAX_SUBMISSIONS times; submission_count is the source of truth.
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
from app.database.models import SAEAssessment, SAEInvitationToken, SAEStudent, SAESubmission, User


# ── Code generation ────────────────────────────────────────────────────────────

def _generate_student_code(assessment_id: uuid.UUID, student_number: int) -> str:
    """
    Produces a globally unique code like SAE-2025-A1B2-001.
    The 4-char assessment hash prevents collisions when multiple assessments
    both have "Student 1".
    """
    year = datetime.now().year
    assessment_hash = str(assessment_id).replace("-", "")[:4].upper()
    return f"SAE-{year}-{assessment_hash}-{student_number:03d}"


def _generate_invitation_token() -> str:
    """256-bit URL-safe random token (43 chars)."""
    return secrets.token_urlsafe(32)


def _build_invitation_url(token: str) -> str:
    base = settings.frontend_url.rstrip("/")
    return f"{base}/sae/setup/{token}"


# ── Assessment CRUD ────────────────────────────────────────────────────────────

def create_assessment(
    db: Session,
    publisher_id: uuid.UUID,
    name: str,
    description: Optional[str] = None,
    course_id: Optional[uuid.UUID] = None,
) -> SAEAssessment:
    """Create a new assessment for a publisher, optionally linked to a course."""
    assessment = SAEAssessment(
        publisher_id=publisher_id,
        course_id=course_id,
        name=name,
        description=description,
        is_active=True,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


def get_publisher_assessments(
    db: Session,
    publisher_id: uuid.UUID,
) -> list[SAEAssessment]:
    """Return all assessments belonging to this publisher, newest first."""
    return (
        db.query(SAEAssessment)
        .filter(SAEAssessment.publisher_id == publisher_id)
        .order_by(SAEAssessment.created_at.desc())
        .all()
    )


def get_assessment_by_id(
    db: Session,
    assessment_id: uuid.UUID,
) -> Optional[SAEAssessment]:
    return db.query(SAEAssessment).filter(SAEAssessment.id == assessment_id).first()


# ── Batch student creation ─────────────────────────────────────────────────────

def create_student_batch(
    db: Session,
    publisher_id: uuid.UUID,
    assessment_id: uuid.UUID,
    count: int,
    expires_days: Optional[int] = None,
) -> list[SAEStudent]:
    """
    Pre-generate `count` student slots + one invitation token each under an assessment.
    Returns the committed SAEStudent rows (with .invitation loaded).
    No emails are sent — the caller receives the invitation URLs.
    """
    # Student numbers are now per-assessment so each cohort starts at 1.
    max_num_row = (
        db.query(func.max(SAEStudent.student_number))
        .filter(SAEStudent.assessment_id == assessment_id)
        .scalar()
    )
    start_from = (max_num_row or 0) + 1

    expires_at: Optional[datetime] = None
    if expires_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    new_students: list[SAEStudent] = []
    for i in range(count):
        num = start_from + i
        code = _generate_student_code(assessment_id, num)
        token_value = _generate_invitation_token()

        student = SAEStudent(
            student_number=num,
            student_code=code,
            display_name=f"Student {num}",
            publisher_id=publisher_id,
            assessment_id=assessment_id,
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
    username: Optional[str],
    password: Optional[str],
    country_of_origin: Optional[str],
    curriculum: Optional[str],
) -> tuple[bool, str, Optional[User]]:
    """
    Atomically handles both uses of an invitation link.

    use_count == 0, user_id is None  → first activation: create User, link student.
    use_count == 0, user_id is set   → re-activation after publisher regenerate:
                                        restore credentials on the existing User row.
    use_count == 1                   → second use of original link: update whichever
                                        credential fields were supplied (username and/or
                                        password), increment token_version to invalidate
                                        sessions on other devices.

    After each successful use:
      - use_count is incremented.
      - used_at is refreshed.
      - When use_count reaches 2, is_used is set to True (link permanently expired).

    Returns (success, error_message, user).
    A conflict on username returns (False, "...", None) without touching use_count.
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

    student = db.query(SAEStudent).filter(
        SAEStudent.id == token_row.student_id
    ).first()
    if not student:
        return False, "Student record not found.", None

    placeholder_email = f"sae.{student.student_code.lower()}@noreply.internal"
    use_count = token_row.use_count

    if use_count == 0 and student.user_id is None:
        # ── Path A: first activation — create a new User ────────────────────
        if not username or not password:
            return False, "Username and password are required.", None
        if not country_of_origin or not curriculum:
            return False, "Country of origin and curriculum are required.", None

        conflict = db.query(User).filter(User.username == username).first()
        if conflict:
            return False, "Username already taken. Please choose a different one.", None

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        user = User(
            username=username,
            email=placeholder_email,
            password_hash=password_hash,
            first_name=student.display_name,
            last_name="",
            role="subscriber",
            email_verified=True,
            is_approved=True,
            token_version=1,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(user)
        db.flush()  # populate user.id before writing the FK
        student.user_id = user.id
        student.country_of_origin = country_of_origin
        student.curriculum = curriculum

    elif use_count == 0 and student.user_id is not None:
        # ── Path B: re-activation after publisher regenerate ─────────────────
        # The publisher called regenerate_student_access(), which mangled the
        # existing User's credentials without deleting the row. We update that
        # same row in-place so no submission data is lost.
        if not username or not password:
            return False, "Username and password are required.", None

        existing_user = db.query(User).filter(User.id == student.user_id).first()
        if not existing_user:
            return False, "Linked user account not found. Contact support.", None

        conflict = (
            db.query(User)
            .filter(User.username == username, User.id != existing_user.id)
            .first()
        )
        if conflict:
            return False, "Username already taken. Please choose a different one.", None

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        existing_user.username = username
        existing_user.email = placeholder_email  # restore canonical email
        existing_user.password_hash = password_hash
        existing_user.updated_at = datetime.utcnow()
        user = existing_user

    elif use_count == 1:
        # ── Path C: second use of original link — credential change ──────────
        # The student already has an account. They may update username, password,
        # or both. At least one must be supplied.
        if not student.user_id:
            return False, "No account is linked to this invitation. Please contact your administrator.", None

        existing_user = db.query(User).filter(User.id == student.user_id).first()
        if not existing_user:
            return False, "Linked user account not found. Contact support.", None

        if not username and not password:
            return False, "Please provide a new username, a new password, or both.", None

        if username:
            conflict = (
                db.query(User)
                .filter(User.username == username, User.id != existing_user.id)
                .first()
            )
            if conflict:
                return False, "Username already taken. Please choose a different one.", None
            existing_user.username = username

        if password:
            existing_user.password_hash = bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")

        # Increment token_version so any JWT issued before this moment is rejected
        # on the next authenticated request, forcing a re-login on other devices.
        existing_user.token_version = (existing_user.token_version or 1) + 1
        existing_user.updated_at = datetime.utcnow()
        user = existing_user

    else:
        # Defensive: use_count >= 2 should have been caught by is_used check above.
        return False, "This invitation link has already been used.", None

    # ── Common: mark activated, consume one use of the token ─────────────────
    student.is_activated = True
    student.activated_at = datetime.utcnow()

    token_row.use_count += 1
    token_row.used_at = datetime.utcnow()
    if token_row.use_count >= 2:
        token_row.is_used = True  # permanently expire after second use

    db.commit()
    db.refresh(user)
    db.refresh(student)

    return True, "", user


# ── Access regeneration ────────────────────────────────────────────────────────

def regenerate_student_access(
    db: Session,
    student: SAEStudent,
) -> tuple[str, str]:
    """
    Resets a student's credentials so they can choose a new username/password
    via a fresh invitation link.

    What this does:
    - Mangles the existing User row's credentials (username, email, password)
      so the student cannot log in with old details.  The row is NOT deleted —
      no student data or submissions are affected.
    - Marks all currently-unused invitation tokens for this student as used.
    - Resets sae_students.is_activated to False (keeps user_id pointing at the
      same User row so it is preserved).
    - Inserts a new SAEInvitationToken.

    The student's next step is to open the returned URL and go through the
    normal setup flow, which will update the same User row with new credentials.

    Returns (invitation_url, token_value).
    Raises ValueError if the student has not been activated yet.
    """
    if not student.is_activated:
        raise ValueError("Student is not activated — nothing to regenerate.")

    # Re-fetch with a row lock to prevent concurrent regenerations.
    student = (
        db.query(SAEStudent)
        .filter(SAEStudent.id == student.id)
        .with_for_update()
        .first()
    )

    # Mangle existing User credentials so the student cannot log in any more.
    # We intentionally keep the row (and all linked submissions) intact.
    if student.user_id:
        old_user = db.query(User).filter(User.id == student.user_id).first()
        if old_user:
            rand = secrets.token_hex(6)
            # Free up the canonical username/email slots so re-activation can
            # reclaim them without hitting unique-constraint errors.
            old_user.username = f"__reset_{rand}_{student.student_code.lower()}__"
            old_user.email = (
                f"__reset_{rand}.{student.student_code.lower()}@noreply.internal"
            )
            # Hash a random secret nobody knows — effectively disables login.
            old_user.password_hash = bcrypt.hashpw(
                secrets.token_bytes(32), bcrypt.gensalt()
            ).decode("utf-8")

    # Invalidate any unused tokens that are still floating around.
    db.query(SAEInvitationToken).filter(
        SAEInvitationToken.student_id == student.id,
        SAEInvitationToken.is_used == False,  # noqa: E712
    ).update({"is_used": True, "used_at": datetime.utcnow()})

    # Reset activation state — user_id is intentionally kept.
    student.is_activated = False

    # Issue a fresh invitation token.
    new_token_value = _generate_invitation_token()
    new_token = SAEInvitationToken(
        student_id=student.id,
        token=new_token_value,
    )
    db.add(new_token)
    db.commit()

    return _build_invitation_url(new_token_value), new_token_value


# ── File storage ───────────────────────────────────────────────────────────────

def build_submission_dir(student_code: str, submission_number: int) -> Path:
    """Per-submission upload directory so files from different submissions never overwrite."""
    submission_dir = Path(settings.upload_dir) / "sae" / student_code / str(submission_number)
    submission_dir.mkdir(parents=True, exist_ok=True)
    return submission_dir


# ── Grading + submission creation ──────────────────────────────────────────────

MAX_SUBMISSIONS = 5

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
    then persists a new SAESubmission row.

    Flow:
      1. Re-fetch SAEStudent with SELECT FOR UPDATE to serialise concurrent requests.
      2. Enforce the MAX_SUBMISSIONS limit (409 if reached).
      3. Write files to a per-submission directory so nothing is overwritten.
      4. Grade via the LLM fallback chain.
      5. Deactivate the previous active submission.
      6. Insert the new submission (submission_number = submission_count + 1, is_active=True).
      7. Update SAEStudent counters and commit.

    Raises HTTPException on limit breach or grading failure.
    """
    from app.llm.fallback_provider import get_fallback_provider
    from app.llm.provider import StudentFiles
    from fastapi import HTTPException, status

    # Step 1 — row lock prevents two simultaneous submissions from both passing the limit check.
    locked_student = (
        db.query(SAEStudent)
        .filter(SAEStudent.id == student.id)
        .with_for_update()
        .first()
    )

    # Step 2 — submission limit
    if locked_student.submission_count >= MAX_SUBMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You have reached the maximum number of submissions ({MAX_SUBMISSIONS}).",
        )

    new_submission_number = locked_student.submission_count + 1

    # Step 3 — write files before grading so the path is ready for the DB row.
    submission_dir = build_submission_dir(locked_student.student_code, new_submission_number)
    hw_path = submission_dir / "handwritten.pdf"
    wa_path = submission_dir / "webassign.pdf"
    hw_path.write_bytes(handwritten_bytes)
    wa_path.write_bytes(webassign_bytes)

    # Step 4 — grade via LLM
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

    # Step 5 — deactivate the previous active submission (if any).
    db.query(SAESubmission).filter(
        SAESubmission.student_id == locked_student.id,
        SAESubmission.is_active == True,  # noqa: E712
    ).update({"is_active": False}, synchronize_session=False)

    # Step 6 — insert the new submission.
    submission = SAESubmission(
        student_id=locked_student.id,
        submission_number=new_submission_number,
        is_active=True,
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

    # Step 7 — update student counters.
    locked_student.submission_count = new_submission_number
    locked_student.submitted_at = datetime.utcnow()

    db.commit()
    db.refresh(submission)
    return submission


# ── Submission history helpers ─────────────────────────────────────────────────

def get_student_submissions(
    db: Session,
    sae_student: SAEStudent,
) -> list[SAESubmission]:
    """All submissions for this student, oldest first."""
    return (
        db.query(SAESubmission)
        .filter(SAESubmission.student_id == sae_student.id)
        .order_by(SAESubmission.submission_number.asc())
        .all()
    )


def get_student_submission_by_id(
    db: Session,
    submission_id: uuid.UUID,
    sae_student: SAEStudent,
) -> Optional[SAESubmission]:
    """Return the submission if it belongs to this student, None otherwise."""
    return (
        db.query(SAESubmission)
        .filter(
            SAESubmission.id == submission_id,
            SAESubmission.student_id == sae_student.id,
        )
        .first()
    )


# ── Dashboard helpers ──────────────────────────────────────────────────────────

def get_publisher_students(
    db: Session,
    publisher_id: uuid.UUID,
    assessment_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
) -> list[SAEStudent]:
    """
    Return students for a publisher.
    Pass assessment_id to scope to a single cohort; omit for all students across all assessments.
    """
    q = db.query(SAEStudent).filter(SAEStudent.publisher_id == publisher_id)
    if assessment_id is not None:
        q = q.filter(SAEStudent.assessment_id == assessment_id)
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
