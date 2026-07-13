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

import asyncio
import base64
import copy
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from sqlalchemy import func, update
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
    base = settings.autograder_frontend_url.rstrip("/")
    return f"{base}/sae/setup/{token}"


# ── Assessment CRUD ────────────────────────────────────────────────────────────

def create_assessment(
    db: Session,
    publisher_id: uuid.UUID,
    name: str,
    description: Optional[str] = None,
    course_id: Optional[uuid.UUID] = None,
    grading_prompt_template_id: Optional[uuid.UUID] = None,
    avatar_id: Optional[uuid.UUID] = None,
) -> SAEAssessment:
    """
    Create a new assessment for a publisher, optionally linked to a course and/or avatar.

    Grading prompt snapshot priority:
      1. grading_prompt_template_id (explicit template) — resolved and frozen.
      2. avatar_id — grading.assessment prompt resolved from avatar's AvatarPromptConfig.
      3. Neither — snapshot is seeded from the hardcoded system default (autograder_cache).
    Every assessment is guaranteed to have a non-null snapshot after creation.
    """
    from app.services.prompt_resolution_service import PromptResolutionService
    from app.services.gemini_file_cache import autograder_cache

    grading_prompt_snapshot: Optional[str] = None
    if grading_prompt_template_id is not None:
        grading_prompt_snapshot = PromptResolutionService()._resolve_direct_template(
            db, grading_prompt_template_id
        )
    elif avatar_id is not None:
        grading_prompt_snapshot = PromptResolutionService().resolve(
            db, avatar_id, "grading.assessment"
        )

    # Guarantee a non-null snapshot so grading never falls through to the
    # resolution service at run time.  The cache is always loaded by the time
    # any publisher request reaches this path (checked at the API layer).
    if grading_prompt_snapshot is None:
        grading_prompt_snapshot = autograder_cache.grading_prompt

    assessment = SAEAssessment(
        publisher_id=publisher_id,
        course_id=course_id,
        name=name,
        description=description,
        is_active=True,
        grading_prompt_template_id=grading_prompt_template_id,
        grading_prompt_snapshot=grading_prompt_snapshot,
        avatar_id=avatar_id,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


def link_avatar_to_assessment(
    db: Session,
    assessment: SAEAssessment,
    avatar_id: Optional[uuid.UUID],
) -> SAEAssessment:
    """
    Link (or unlink) an avatar to an existing assessment and re-snapshot the
    grading prompt from the avatar's current grading.assessment AvatarPromptConfig.

    Passing avatar_id=None unlinks the avatar. The existing grading_prompt_snapshot
    is cleared so grading falls back to the system default going forward.

    The snapshot is intentionally re-frozen here — callers must make an explicit
    PATCH request to update it. Auto-updating on every avatar prompt change would
    break fairness for in-progress assessments.
    """
    from app.services.prompt_resolution_service import PromptResolutionService

    assessment.avatar_id = avatar_id

    if avatar_id is not None:
        snapshot = PromptResolutionService().resolve(db, avatar_id, "grading.assessment")
        assessment.grading_prompt_snapshot = snapshot
        assessment.grading_prompt_template_id = None
    else:
        assessment.grading_prompt_snapshot = None
        assessment.grading_prompt_template_id = None

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


def update_assessment_prompt(
    db: Session,
    assessment: SAEAssessment,
    grading_prompt: Optional[str],
) -> SAEAssessment:
    """
    Write a new grading prompt snapshot to an assessment.

    Passing grading_prompt=None (or an empty string) resets the snapshot to the
    hardcoded system default loaded from data/grading_prompt.txt at startup.
    The snapshot is what grade_and_save_submission reads at run time — nothing
    else in the grading pipeline is touched.
    """
    from app.services.gemini_file_cache import autograder_cache

    assessment.grading_prompt_snapshot = grading_prompt or autograder_cache.grading_prompt
    db.commit()
    db.refresh(assessment)
    return assessment


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


# ── Student deletion ──────────────────────────────────────────────────────────

def delete_student(db: Session, student: SAEStudent) -> None:
    """
    Permanently remove a student slot that has never been activated and has no submissions.
    The invitation token cascades automatically via the ORM relationship.
    Raises ValueError for activated students or those with submissions.
    """
    if student.is_activated:
        raise ValueError("Cannot delete an activated student. Use regenerate access instead.")
    if student.submission_count > 0:
        raise ValueError("Cannot delete a student who has already submitted.")
    db.delete(student)
    db.commit()


# ── Multi-assessment enrollment ────────────────────────────────────────────────

def ensure_student_access(
    db: Session,
    user_id: uuid.UUID,
    publisher_id: uuid.UUID,
    country_of_origin: Optional[str] = None,
    curriculum: Optional[str] = None,
) -> list[SAEStudent]:
    """
    Guarantee the user has an activated SAEStudent row for every active assessment
    owned by publisher_id. Safe to call repeatedly — fully idempotent.

    For each active assessment (ordered by id to prevent deadlocks):
      1. Skip if the user already has an activated row for that assessment.
      2. Lock the assessment row to serialise concurrent enrollments.
      3. Re-check after the lock (another session may have just enrolled).
      4. Claim an existing unactivated pre-created slot so publisher-assigned
         student numbers and codes are preserved.
      5. If no pre-created slot is available, create a fresh row.

    country_of_origin / curriculum are propagated to any newly created rows.
    When both are None the function looks them up from the user's existing rows.

    Does NOT commit — the caller is responsible for committing the transaction.
    Flushes so that changes are visible to subsequent queries in the same session.
    """
    # If educational metadata not supplied, copy from an existing row for this publisher.
    if country_of_origin is None or curriculum is None:
        source = (
            db.query(SAEStudent)
            .filter(
                SAEStudent.publisher_id == publisher_id,
                SAEStudent.user_id == user_id,
                SAEStudent.country_of_origin.isnot(None),
            )
            .first()
        )
        if source:
            country_of_origin = country_of_origin or source.country_of_origin
            curriculum = curriculum or source.curriculum

    # Sort by id for deterministic lock ordering — prevents deadlocks when two
    # sessions concurrently enroll different users in the same publisher's assessments.
    active_assessments = (
        db.query(SAEAssessment)
        .filter(
            SAEAssessment.publisher_id == publisher_id,
            SAEAssessment.is_active == True,  # noqa: E712
        )
        .order_by(SAEAssessment.id)
        .all()
    )

    for assessment in active_assessments:
        # Fast-path: already enrolled — no lock needed.
        already = (
            db.query(SAEStudent)
            .filter(
                SAEStudent.assessment_id == assessment.id,
                SAEStudent.user_id == user_id,
            )
            .first()
        )
        if already:
            continue

        # Lock the assessment row so concurrent sessions serialise here.
        db.query(SAEAssessment).filter(
            SAEAssessment.id == assessment.id
        ).with_for_update().first()

        # Re-check after acquiring the lock.
        already = (
            db.query(SAEStudent)
            .filter(
                SAEStudent.assessment_id == assessment.id,
                SAEStudent.user_id == user_id,
            )
            .first()
        )
        if already:
            continue

        now = datetime.now(timezone.utc)

        # Prefer claiming an existing unactivated publisher-created slot so that
        # student numbers/codes match what the publisher generated.
        slot = (
            db.query(SAEStudent)
            .filter(
                SAEStudent.assessment_id == assessment.id,
                SAEStudent.user_id.is_(None),
                SAEStudent.is_activated == False,  # noqa: E712
            )
            .first()
        )

        if slot:
            slot.user_id = user_id
            slot.is_activated = True
            slot.activated_at = now
            if country_of_origin:
                slot.country_of_origin = country_of_origin
            if curriculum:
                slot.curriculum = curriculum
        else:
            max_num = (
                db.query(func.max(SAEStudent.student_number))
                .filter(SAEStudent.assessment_id == assessment.id)
                .scalar()
            ) or 0
            new_row = SAEStudent(
                student_number=max_num + 1,
                student_code=_generate_student_code(assessment.id, max_num + 1),
                display_name=f"Student {max_num + 1}",
                publisher_id=publisher_id,
                assessment_id=assessment.id,
                user_id=user_id,
                is_activated=True,
                activated_at=now,
                country_of_origin=country_of_origin,
                curriculum=curriculum,
            )
            db.add(new_row)

    db.flush()

    return (
        db.query(SAEStudent)
        .filter(
            SAEStudent.publisher_id == publisher_id,
            SAEStudent.user_id == user_id,
        )
        .all()
    )


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
    is_existing_account: bool = False,
) -> tuple[bool, str, Optional[User], Optional[SAEStudent]]:
    """
    Atomically handles both uses of an invitation link.

    use_count == 0, user_id is None, username is new
                                     → Path A: first activation — create User, link student.
    use_count == 0, user_id is None, username belongs to existing User with matching password
                                     → Path A2: existing-account login — link that User to this
                                        student slot and enroll in all active assessments.
    use_count == 0, user_id is set   → Path B: re-activation after publisher regenerate —
                                        restore credentials on the existing User row.
    use_count == 1                   → Path C: second use of original link — update whichever
                                        credential fields were supplied (username and/or
                                        password), increment token_version to invalidate
                                        sessions on other devices.

    Paths A, A2, and B all call ensure_student_access so the user gains rows for every
    active assessment owned by the publisher, not just the one tied to this token.

    After each successful use:
      - use_count is incremented.
      - used_at is refreshed.
      - When use_count reaches 2, is_used is set to True (link permanently expired).

    Returns (success, error_message, user, activated_student).
    On failure returns (False, reason, None, None) without touching use_count.
    """
    # Lock the token row to prevent two simultaneous requests from both succeeding.
    token_row = (
        db.query(SAEInvitationToken)
        .filter(SAEInvitationToken.token == token_value)
        .with_for_update()
        .first()
    )
    if not token_row:
        return False, "Invalid invitation link.", None, None
    if token_row.is_used:
        return False, "This invitation link has already been used.", None, None
    if token_row.expires_at is not None:
        exp = token_row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            return False, "This invitation link has expired.", None, None

    student = db.query(SAEStudent).filter(
        SAEStudent.id == token_row.student_id
    ).first()
    if not student:
        return False, "Student record not found.", None, None

    placeholder_email = f"sae.{student.student_code.lower()}@noreply.internal"
    use_count = token_row.use_count

    if use_count == 0 and student.user_id is None:
        if not username or not password:
            return False, "Username and password are required.", None, None

        existing_user = db.query(User).filter(User.username == username).first()

        if existing_user:
            # ── Path A2: existing account — verify password and link ─────────
            if not bcrypt.checkpw(
                password.encode("utf-8"),
                existing_user.password_hash.encode("utf-8"),
            ):
                if is_existing_account:
                    return False, "Incorrect password. Please try again.", None, None
                # New-account path: username clash — keep the generic message.
                return False, "Username already taken. Please choose a different one.", None, None
            user = existing_user
            student.user_id = user.id
            # Preserve any educational metadata supplied by the form (may be empty
            # for returning users who skipped those fields).
            if country_of_origin:
                student.country_of_origin = country_of_origin
            if curriculum:
                student.curriculum = curriculum
        else:
            # ── Path A: first activation — create a new User ─────────────────
            if is_existing_account:
                # Student said they have an account but no matching username found.
                return False, "No account found with that username. Please check your username and try again.", None, None
            if not country_of_origin or not curriculum:
                return False, "Country of origin and curriculum are required.", None, None

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
            return False, "Username and password are required.", None, None

        existing_user = db.query(User).filter(User.id == student.user_id).first()
        if not existing_user:
            return False, "Linked user account not found. Contact support.", None, None

        conflict = (
            db.query(User)
            .filter(User.username == username, User.id != existing_user.id)
            .first()
        )
        if conflict:
            return False, "Username already taken. Please choose a different one.", None, None

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
            return False, "No account is linked to this invitation. Please contact your administrator.", None, None

        existing_user = db.query(User).filter(User.id == student.user_id).first()
        if not existing_user:
            return False, "Linked user account not found. Contact support.", None, None

        if not username and not password:
            return False, "Please provide a new username, a new password, or both.", None, None

        if username:
            conflict = (
                db.query(User)
                .filter(User.username == username, User.id != existing_user.id)
                .first()
            )
            if conflict:
                return False, "Username already taken. Please choose a different one.", None, None
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
        return False, "This invitation link has already been used.", None, None

    # ── Common: mark activated, consume one use of the token ─────────────────
    student.is_activated = True
    student.activated_at = datetime.utcnow()

    token_row.use_count += 1
    token_row.used_at = datetime.utcnow()
    if token_row.use_count >= 2:
        token_row.is_used = True  # permanently expire after second use

    # Enroll the user in all active assessments for this publisher.
    # Runs for Paths A, A2, and B (use_count was 0). Skipped for Path C
    # (credential change only — no new assessment rows needed).
    if use_count == 0:
        db.flush()  # make student.user_id and is_activated visible within this tx
        ensure_student_access(
            db,
            user_id=user.id,
            publisher_id=student.publisher_id,
            country_of_origin=student.country_of_origin,
            curriculum=student.curriculum,
        )

    db.commit()
    db.refresh(user)
    db.refresh(student)

    return True, "", user, student


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
    request_id: Optional[str] = None,
) -> SAESubmission:
    """
    Runs the LLM grading pipeline (same fallback chain as the Math autograder)
    then persists a new SAESubmission row.

    Flow:
      1. Re-fetch SAEStudent with SELECT FOR UPDATE (short-lived lock).
      2. Enforce the MAX_SUBMISSIONS limit (409 if reached).
      3. Increment submission_count and commit — releases the row lock immediately
         so concurrent submissions for this student can start their own Gemini calls.
      4. Write files to a per-submission directory and grade via the LLM fallback
         chain concurrently (no DB lock held during this step).
      5. On grading/storage failure: roll back the counter so the slot isn't wasted.
      6. Deactivate the previous active submission.
      7. Insert the new submission (submission_number = new_submission_number, is_active=True).
      8. Update SAEStudent.submitted_at and commit.

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

    # Step 2 — submission limit.
    if locked_student.submission_count >= MAX_SUBMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You have reached the maximum number of submissions ({MAX_SUBMISSIONS}).",
        )

    new_submission_number = locked_student.submission_count + 1

    # Capture values needed after commit — commit expires ORM object attributes.
    student_id = locked_student.id
    student_code = locked_student.student_code

    from app.services.r2_service import r2

    hw_key = f"autograder/sae/{student_code}/{new_submission_number}/handwritten.pdf"
    wa_key = f"autograder/sae/{student_code}/{new_submission_number}/webassign.pdf"

    # Resolve grading prompt before committing (needs the assessment relationship).
    grading_prompt_for_run: str | None = None
    if locked_student.assessment and locked_student.assessment.grading_prompt_snapshot:
        grading_prompt_for_run = locked_student.assessment.grading_prompt_snapshot
    else:
        from app.services.prompt_resolution_service import PromptResolutionService
        grading_prompt_for_run = PromptResolutionService()._resolve_system_default(
            db, "grading.assessment"
        )

    # Step 3 — increment counter and commit immediately to release the row lock.
    # Concurrent submissions for this student can now pass the limit check and
    # start their own Gemini calls without waiting for this one to finish.
    locked_student.submission_count = new_submission_number
    db.commit()

    # Steps 4 — storage and LLM grading run concurrently (no DB lock held).
    #
    # The LLM only needs in-memory bytes (StudentFiles); stored file paths are
    # only needed for the DB row written AFTER grading.  Running them in parallel
    # hides R2/disk latency (typically 6–20 s) behind the LLM call (30–120 s).
    # R2 uploads use asyncio.to_thread so boto3 (sync) cannot block the event loop.

    # b64 encode both PDFs off the main thread — CPU-bound for large files.
    hw_b64, wa_b64 = await asyncio.gather(
        asyncio.to_thread(lambda: base64.b64encode(handwritten_bytes).decode("utf-8")),
        asyncio.to_thread(lambda: base64.b64encode(webassign_bytes).decode("utf-8")),
    )
    student_files = StudentFiles(webassign_b64=wa_b64, handwritten_b64=hw_b64)

    fp = get_fallback_provider()

    if r2.enabled:
        async def _store_r2() -> tuple[str, str]:
            await asyncio.gather(
                asyncio.to_thread(r2.upload, hw_key, handwritten_bytes),
                asyncio.to_thread(r2.upload, wa_key, webassign_bytes),
            )
            return hw_key, wa_key

        storage_coro = _store_r2()
    else:
        async def _store_local() -> tuple[str, str]:
            def _write() -> tuple[str, str]:
                sub_dir = build_submission_dir(student_code, new_submission_number)
                hw_path = sub_dir / "handwritten.pdf"
                wa_path = sub_dir / "webassign.pdf"
                hw_path.write_bytes(handwritten_bytes)
                wa_path.write_bytes(webassign_bytes)
                return str(hw_path), str(wa_path)
            return await asyncio.to_thread(_write)

        storage_coro = _store_local()

    try:
        (hw_stored, wa_stored), result = await asyncio.gather(
            storage_coro,
            fp.grade(student_files, request_id=request_id, grading_prompt=grading_prompt_for_run),
        )
    except RuntimeError as exc:
        msg = str(exc)
        # Step 5 — roll back the counter so the student doesn't lose a submission slot.
        # Use a relative decrement (not absolute set) so concurrent failures compose correctly.
        db.execute(
            update(SAEStudent)
            .where(SAEStudent.id == student_id)
            .values(submission_count=SAEStudent.submission_count - 1)
        )
        db.commit()
        prefix = "File storage failed" if "R2 upload" in msg or "upload failed" in msg.lower() else "Grading failed"
        if request_id:
            from app.llm.event_bus import event_bus as _event_bus
            await _event_bus.publish(request_id, {
                "event": "grading_failed",
                "request_id": request_id,
                "provider": None,
                "reason": msg,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{prefix}: {msg}",
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

    # Step 6 — deactivate the previous active submission (if any).
    db.query(SAESubmission).filter(
        SAESubmission.student_id == student_id,
        SAESubmission.is_active == True,  # noqa: E712
    ).update({"is_active": False}, synchronize_session=False)

    # Step 7 — insert the new submission.
    submission = SAESubmission(
        student_id=student_id,
        submission_number=new_submission_number,
        is_active=True,
        submitted_by_publisher=submitted_by_publisher,
        publisher_user_id=publisher_user_id,
        handwritten_filename=handwritten_filename,
        handwritten_file_path=hw_stored,
        webassign_filename=webassign_filename,
        webassign_file_path=wa_stored,
        score=result.score,
        overall_confidence=result_data.get("overall_confidence"),
        review_required=result_data["submission_review_required"],
        result_json=result_data,
    )
    db.add(submission)

    # Step 8 — update submitted_at (submission_count already committed in Step 3).
    db.execute(
        update(SAEStudent)
        .where(SAEStudent.id == student_id)
        .values(submitted_at=datetime.utcnow())
    )

    db.commit()
    db.refresh(submission)

    if request_id:
        from app.llm.event_bus import event_bus as _event_bus
        await _event_bus.publish(request_id, {
            "event": "grading_complete",
            "request_id": request_id,
            "submission_id": str(submission.id),
            "provider": result.model_used,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })

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
