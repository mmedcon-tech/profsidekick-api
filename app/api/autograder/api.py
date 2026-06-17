import base64
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, status, Depends, Form
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.config import settings
from app.database.connection import get_db
from app.database.models import AutograderSubmission, Student, User
from app.dependencies.auth import get_current_user
from app.api.autograder.cache import autograder_cache

router = APIRouter(prefix="/api/autograder", tags=["autograder"])

def require_autograder_role(current_user: User, allowed_roles: list[str]) -> User:
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this autograder resource.",
        )
    return current_user


def clean_json(text: str) -> str:
    return text.replace("```json", "").replace("```", "").strip()


@router.post("/grade")
async def grade_submission(
    student_answer: UploadFile = File(...),
    webassign_pdf: UploadFile = File(...),
    student_id: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_autograder_role(current_user, ["subscriber"])
    if not autograder_cache.loaded:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Autograder static files not loaded. Check server startup logs.",
        )
    try:
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

        gemini_api_key = settings.gemini_api_key
        model = settings.gemini_model

        print(f"[DEBUG] gemini_api_key loaded: {'SET (len=' + str(len(gemini_api_key)) + ')' if gemini_api_key else 'EMPTY'}")
        print(f"[DEBUG] model: {model}")

        if not gemini_api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gemini key is missing. Set GEMINI_API_KEY in your .env file.",
            )

        webassign_content = await webassign_pdf.read()
        webassign_pdf_base64 = base64.b64encode(webassign_content).decode("utf-8")

        student_content = await student_answer.read()
        student_pdf_base64 = base64.b64encode(student_content).decode("utf-8")

        submission_id = uuid.uuid4()
        submission_dir = Path("uploads") / "autograder" / str(submission_id)
        submission_dir.mkdir(parents=True, exist_ok=True)

        handwritten_orig_filename = student_answer.filename or "handwritten.pdf"
        handwritten_path = submission_dir / "handwritten.pdf"
        handwritten_path.write_bytes(student_content)

        webassign_orig_filename = webassign_pdf.filename or "webassign.pdf"
        webassign_path = submission_dir / "webassign.pdf"
        webassign_path.write_bytes(webassign_content)

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": autograder_cache.grading_prompt},
                        # --- Golden triplet (static benchmark) ---
                        {"inline_data": {"mime_type": "application/pdf", "data": autograder_cache.rubric_b64}},
                        {"inline_data": {"mime_type": "application/pdf", "data": autograder_cache.webassign_solution_b64}},
                        {"inline_data": {"mime_type": "application/pdf", "data": autograder_cache.solution_b64}},
                        # --- Student submission (dynamic) ---
                        {"inline_data": {"mime_type": "application/pdf", "data": webassign_pdf_base64}},
                        {"inline_data": {"mime_type": "application/pdf", "data": student_pdf_base64}},
                    ],
                },
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }

        async with httpx.AsyncClient(timeout=350.0) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_api_key}",
                headers={"Content-Type": "application/json"},
                json=payload,
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Gemini API error {response.status_code}: {response.text}",
            )

        data = response.json()
        raw_output = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")
        if not raw_output:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Model returned empty content. Full response: {data}",
            )
        cleaned_output = clean_json(raw_output)
        print("RAW MODEL OUTPUT:")
        print(cleaned_output)

        try:
            parsed = json.loads(cleaned_output)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Model returned invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}"
            )

        questions = []
        for q in parsed.get("questions", []):
            question_id = str(q.get("id", "")).strip()
            raw_max_score_value = q.get("max_score")
            if isinstance(raw_max_score_value, (int, float)):
                max_score = float(raw_max_score_value)
            else:
                max_score = 0

            if isinstance(q.get("score"), (int, float)):
                safe_score = max(0, min(q["score"], max_score))
            else:
                safe_score = None

            grading_basis = q.get("grading_basis") if isinstance(q.get("grading_basis"), dict) else {}

            questions.append(
                {
                    "id": question_id,
                    "max_score": max_score,
                    "score": safe_score,
                    "grading_basis": {
                        "understanding_level": grading_basis.get("understanding_level", "none"),
                        "error_severity": grading_basis.get("error_severity", "fundamental"),
                        "work_completeness": grading_basis.get("work_completeness", "blank"),
                        "recommended_credit_percent": grading_basis.get("recommended_credit_percent", 0),
                    },
                    "official_answer_summary": q.get("official_answer_summary", ""),
                    "student_answer_summary": q.get("student_answer_summary", ""),
                    "confidence": q.get("confidence", "low"),
                    "readability": q.get("readability", "low"),
                    "feedback": q.get("feedback", ""),
                    "grey_areas": q.get("grey_areas")
                    if isinstance(q.get("grey_areas"), list)
                    else [],
                    "human_review_required": bool(q.get("human_review_required", False)),
                    "human_review_reason": q.get("human_review_reason"),
                }
            )

        raw_max_score = sum(
            q["max_score"] if isinstance(q["max_score"], (int, float)) else 0
            for q in questions
        )

        raw_score = sum(
            q["score"] if isinstance(q["score"], (int, float)) else 0
            for q in questions
        )

        score = raw_score

        null_score_reasons = [
            f"Question {q['id']} could not be scored."
            for q in questions
            if q["score"] is None
        ]

        review_reasons = []
        if isinstance(parsed.get("submission_review_reasons"), list):
            review_reasons.extend(parsed["submission_review_reasons"])

        review_reasons.extend(
            [
                f"Question {q['id']}: {q['human_review_reason'] or 'Review required.'}"
                for q in questions
                if q["human_review_required"]
            ]
        )

        review_reasons.extend(null_score_reasons)

        result_data = {
            "raw_score": raw_score,
            "raw_max_score": raw_max_score,
            "score": score,
            "submission_review_required": bool(parsed.get("submission_review_required"))
            or len(review_reasons) > 0,
            "submission_review_reasons": review_reasons,
            "overall_feedback": parsed.get("overall_feedback", ""),
            "questions": questions,
            "details": {
                "filename": handwritten_orig_filename,
                "file_size": len(student_content),
                "model": model,
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
            # Legacy fields (kept until Phase 5 — populated from student record)
            student_user_id=current_user.id,
            student_net_id=student.student_code,
            student_name=student.display_name,
            filename=handwritten_orig_filename,
            file_path=str(handwritten_path),
            score=score,
            review_required=result_data["submission_review_required"],
            result_json=result_data,
            is_active=True,
            created_at=datetime.utcnow(),
        )

        db.add(submission)
        db.commit()
        db.refresh(submission)

        return {
            **result_data,
            "submission_id": str(submission.id),
            "message": "Submission graded and saved successfully.",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Autograder failed: {str(e)}",
        )


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
        "raw_max_score": submission.result_json.get("raw_max_score") if submission.result_json else None,
        "review_required": submission.review_required,
        "created_at": submission.created_at.isoformat() if submission.created_at else None,
    }


@router.get("/submissions")
async def get_submissions(
    student_id: Optional[str] = Query(default=None),
    version: Optional[int] = Query(default=None),
    review_required: Optional[bool] = Query(default=None),
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
    else:
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

    return [_submission_list_row(sub, stu) for sub, stu in results]


@router.get("/submissions/me/latest")
async def get_my_latest_submission(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_autograder_role(current_user, ["subscriber"])

    submission = (
        db.query(AutograderSubmission)
        .filter(
            AutograderSubmission.student_user_id == current_user.id,
            AutograderSubmission.is_active == True,
        )
        .first()
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
        "created_at": submission.created_at.isoformat() if submission.created_at else None,
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

    if current_user.role == "subscriber" and submission.student_user_id != current_user.id:
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
        "created_at": submission.created_at.isoformat()
        if submission.created_at
        else None,
        "result_json": submission.result_json,
    }