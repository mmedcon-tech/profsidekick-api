import base64
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import AutograderSubmission, Student, User
from app.dependencies.auth import get_current_user
from app.llm.event_bus import event_bus
from app.llm.fallback_provider import get_fallback_provider
from app.llm.provider import StudentFiles
from app.services.gemini_file_cache import autograder_cache

router = APIRouter(prefix="/api/autograder", tags=["autograder"])


def require_autograder_role(current_user: User, allowed_roles: list[str]) -> User:
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this autograder resource.",
        )
    return current_user


# ---------------------------------------------------------------------------
# Grading endpoint
# ---------------------------------------------------------------------------

@router.post("/grade")
async def grade_submission(
    student_answer: UploadFile = File(...),
    webassign_pdf: UploadFile = File(...),
    student_id: str = Form(...),
    request_id: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_autograder_role(current_user, ["subscriber"])
    t_request_start = time.monotonic()
    _rid = request_id or None

    print(
        f"[TRACE] grade_request_received "
        f"request_id={_rid or 'no-sse'} "
        f"student_id={student_id} "
        f"user_id={current_user.id} "
        f"sse_enabled={bool(_rid)}"
    )

    if not autograder_cache.loaded:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Autograder not ready. Check server startup logs.",
        )

    try:
        student_uuid = uuid.UUID(student_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid student_id format: {student_id}",
        )

    student = (
        db.query(Student)
        .filter(Student.id == student_uuid)
        .with_for_update()
        .one_or_none()
    )
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student not found: {student_id}",
        )

    try:
        webassign_content = await webassign_pdf.read()
        student_content = await student_answer.read()

        submission_id = uuid.uuid4()
        submission_dir = Path("uploads") / "autograder" / str(submission_id)
        submission_dir.mkdir(parents=True, exist_ok=True)

        handwritten_orig_filename = student_answer.filename or "handwritten.pdf"
        handwritten_path = submission_dir / "handwritten.pdf"
        handwritten_path.write_bytes(student_content)

        webassign_orig_filename = webassign_pdf.filename or "webassign.pdf"
        webassign_path = submission_dir / "webassign.pdf"
        webassign_path.write_bytes(webassign_content)

        print(
            f"[TRACE] student_files_received "
            f"request_id={_rid or 'no-sse'} "
            f"handwritten_filename={handwritten_orig_filename} "
            f"handwritten_bytes={len(student_content)} "
            f"webassign_filename={webassign_orig_filename} "
            f"webassign_bytes={len(webassign_content)}"
        )

        student_files = StudentFiles(
            webassign_b64=base64.b64encode(webassign_content).decode("utf-8"),
            handwritten_b64=base64.b64encode(student_content).decode("utf-8"),
        )

        fp = get_fallback_provider()
        print(
            f"[TRACE] fallback_provider_selected "
            f"request_id={_rid or 'no-sse'} "
            f"provider_chain={fp.provider_names}"
        )

        try:
            result = await fp.grade(student_files, request_id=_rid)
        except RuntimeError as exc:
            total_ms = int((time.monotonic() - t_request_start) * 1000)
            print(
                f"[TRACE] grade_request_failed "
                f"request_id={_rid or 'no-sse'} "
                f"total_duration_ms={total_ms} "
                f"error={str(exc)[:300]}"
            )
            if _rid:
                await event_bus.publish(_rid, {
                    "event": "grading_failed",
                    "request_id": _rid,
                    "provider": None,
                    "reason": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                })
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
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
                "filename": handwritten_orig_filename,
                "file_size": len(student_content),
                "model": result.model_used,
                "source": result.source,
                "system_files": ["rubric.pdf", "webassign_solution.pdf", "solution.pdf"],
                "webassign_filename": webassign_orig_filename,
            },
        }

        version_count = (
            db.query(func.count(AutograderSubmission.id))
            .filter(AutograderSubmission.student_id == student.id)
            .scalar()
        )
        version_number = version_count + 1

        existing = (
            db.query(AutograderSubmission)
            .filter(
                AutograderSubmission.student_id == student.id,
                AutograderSubmission.is_active == True,
            )
            .first()
        )
        if existing:
            existing.is_active = False

        submission = AutograderSubmission(
            id=submission_id,
            student_id=student.id,
            version_number=version_number,
            submitted_by=current_user.id,
            handwritten_filename=handwritten_orig_filename,
            handwritten_file_path=str(handwritten_path),
            webassign_filename=webassign_orig_filename,
            webassign_file_path=str(webassign_path),
            # Legacy fields kept until Phase 5
            student_user_id=current_user.id,
            student_net_id=student.student_code,
            student_name=student.display_name,
            filename=handwritten_orig_filename,
            file_path=str(handwritten_path),
            score=result.score,
            review_required=result_data["submission_review_required"],
            result_json=result_data,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )

        db.add(submission)
        db.commit()
        db.refresh(submission)

        total_ms = int((time.monotonic() - t_request_start) * 1000)
        print(
            f"[TRACE] grade_request_success "
            f"request_id={_rid or 'no-sse'} "
            f"submission_id={submission_id} "
            f"source={result.source} "
            f"model={result.model_used} "
            f"score={result.score} "
            f"total_duration_ms={total_ms}"
        )
        print(
            f"[TRACE] FINAL_SUMMARY "
            f"request_id={_rid or 'no-sse'} "
            f"total_duration_ms={total_ms} "
            f"provider_chain={fp.provider_names} "
            f"winning_provider={result.source} "
            f"score={result.score} "
            f"final_status=success"
        )

        if _rid:
            await event_bus.publish(_rid, {
                "event": "grading_complete",
                "request_id": _rid,
                "provider": result.model_used,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            })

        from app.config import settings
        response: dict = {
            **result_data,
            "submission_id": str(submission.id),
            "message": "Submission graded and saved successfully.",
        }
        if settings.debug:
            response["debug"] = {
                "sse_enabled": bool(_rid),
                "request_id": _rid,
                "provider_chain_traversed": fp.provider_names,
                "winning_provider": result.source,
                "total_duration_ms": total_ms,
            }
        return response

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Autograder failed: {str(exc)}",
        )


# ---------------------------------------------------------------------------
# Submission read endpoints (unchanged)
# ---------------------------------------------------------------------------

def _submission_list_row(submission: AutograderSubmission, student: Student) -> dict:
    return {
        "id": str(submission.id),
        "student_id": str(student.id),
        "student_code": student.student_code,
        "display_name": student.display_name,
        "version_number": submission.version_number,
        # Legacy fields kept until Phase 5
        "student_net_id": submission.student_net_id,
        "student_name": submission.student_name,
        "score": submission.score,
        "raw_max_score": (
            submission.result_json.get("raw_max_score")
            if submission.result_json
            else None
        ),
        "review_required": submission.review_required,
        "created_at": (
            submission.created_at.isoformat() if submission.created_at else None
        ),
    }


@router.get("/submissions")
async def get_submissions(
    student_id: Optional[str] = Query(default=None),
    version: Optional[int] = Query(default=None),
    review_required: Optional[bool] = Query(default=None),
    all_versions: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_autograder_role(current_user, ["subscriber", "publisher", "admin"])

    if student_id is not None:
        try:
            student_uuid = uuid.UUID(student_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid student_id format: {student_id}",
            )
        query = (
            db.query(AutograderSubmission, Student)
            .join(Student, AutograderSubmission.student_id == Student.id)
            .filter(AutograderSubmission.student_id == student_uuid)
        )
        if version is not None:
            query = query.filter(AutograderSubmission.version_number == version)
        if review_required is not None:
            query = query.filter(AutograderSubmission.review_required == review_required)
        results = query.order_by(AutograderSubmission.version_number.desc()).all()
    elif all_versions:
        # Return every submission across all students, newest first
        query = (
            db.query(AutograderSubmission, Student)
            .join(Student, AutograderSubmission.student_id == Student.id)
        )
        if review_required is not None:
            query = query.filter(AutograderSubmission.review_required == review_required)
        results = query.order_by(AutograderSubmission.created_at.desc()).all()
        print(
            f"[DEBUG] get_submissions all_versions=True "
            f"user_id={current_user.id} "
            f"count={len(results)} "
            f"ids={[str(s.id) for s, _ in results]}"
        )
    else:
        # Default: one row per student (latest version only)
        subq = (
            db.query(
                AutograderSubmission.student_id,
                func.max(AutograderSubmission.version_number).label("max_ver"),
            )
            .group_by(AutograderSubmission.student_id)
            .subquery()
        )
        query = (
            db.query(AutograderSubmission, Student)
            .join(Student, AutograderSubmission.student_id == Student.id)
            .join(
                subq,
                and_(
                    AutograderSubmission.student_id == subq.c.student_id,
                    AutograderSubmission.version_number == subq.c.max_ver,
                ),
            )
        )
        if review_required is not None:
            query = query.filter(AutograderSubmission.review_required == review_required)
        results = query.order_by(AutograderSubmission.created_at.desc()).all()
        print(
            f"[DEBUG] get_submissions latest_per_student "
            f"user_id={current_user.id} "
            f"count={len(results)} "
            f"ids={[str(s.id) for s, _ in results]}"
        )

    return [_submission_list_row(sub, stu) for sub, stu in results]


@router.get("/submissions/me")
async def get_my_submissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all submissions made by the currently authenticated subscriber (student)."""
    require_autograder_role(current_user, ["subscriber"])

    submissions = (
        db.query(AutograderSubmission)
        .filter(AutograderSubmission.student_user_id == current_user.id)
        .order_by(AutograderSubmission.created_at.desc())
        .all()
    )

    print(
        f"[DEBUG] get_my_submissions "
        f"user_id={current_user.id} "
        f"count={len(submissions)} "
        f"ids={[str(s.id) for s in submissions]}"
    )

    return [
        {
            "id": str(s.id),
            "student_net_id": s.student_net_id,
            "student_name": s.student_name,
            "version_number": s.version_number,
            "score": s.score,
            "raw_max_score": s.result_json.get("raw_max_score") if s.result_json else None,
            "review_required": s.review_required,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in submissions
    ]


@router.get("/submissions/me/latest")
async def get_my_latest_submission(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_autograder_role(current_user, ["subscriber"])

    # Order by version_number DESC so we always get the true latest,
    # regardless of the is_active flag (which gets toggled on each new submission).
    submission = (
        db.query(AutograderSubmission)
        .filter(AutograderSubmission.student_user_id == current_user.id)
        .order_by(AutograderSubmission.version_number.desc())
        .first()
    )

    print(
        f"[DEBUG] get_my_latest_submission "
        f"user_id={current_user.id} "
        f"found={'yes' if submission else 'no'} "
        f"submission_id={submission.id if submission else None}"
    )

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No autograder submission found for this student.",
        )

    return {
        "id": str(submission.id),
        "student_net_id": submission.student_net_id,
        "student_name": submission.student_name,
        "score": submission.score,
        "review_required": submission.review_required,
        "created_at": (
            submission.created_at.isoformat() if submission.created_at else None
        ),
        "result_json": submission.result_json,
    }


@router.get("/submissions/{submission_id}")
async def get_submission(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_autograder_role(current_user, ["subscriber", "publisher", "admin"])

    submission = (
        db.query(AutograderSubmission)
        .filter(AutograderSubmission.id == submission_id)
        .first()
    )

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if (
        current_user.role == "subscriber"
        and submission.student_user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own submission feedback.",
        )

    return {
        "id": str(submission.id),
        "student_net_id": submission.student_net_id,
        "student_name": submission.student_name,
        "score": submission.score,
        "review_required": submission.review_required,
        "created_at": (
            submission.created_at.isoformat() if submission.created_at else None
        ),
        "result_json": submission.result_json,
    }
