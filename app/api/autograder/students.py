from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import AutograderSubmission, User
from app.dependencies.auth import require_subscriber
from app.services import student_service

router = APIRouter(prefix="/api/autograder", tags=["autograder"])


class CreateStudentRequest(BaseModel):
    display_name: str


def _student_response(student) -> dict:
    return {
        "student_id": str(student.id),
        "student_code": student.student_code,
        "display_name": student.display_name,
        "created_by": str(student.created_by),
        "created_at": student.created_at.isoformat() if student.created_at else None,
    }


def _submission_response(submission: AutograderSubmission) -> dict:
    return {
        "submission_id": str(submission.id),
        "version_number": submission.version_number,
        "score": submission.score,
        "review_required": submission.review_required,
        "created_at": submission.created_at.isoformat() if submission.created_at else None,
        "result_json": submission.result_json,
    }


@router.post("/students", status_code=status.HTTP_201_CREATED)
async def create_student(
    body: CreateStudentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_subscriber),
):
    if not body.display_name or not body.display_name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="display_name must not be empty.",
        )
    student = student_service.create_student(db, body.display_name.strip(), current_user.id)
    return _student_response(student)


@router.get("/students")
async def list_or_lookup_students(
    code: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_subscriber),
):
    if code is not None:
        student = student_service.get_student_by_code(db, code.strip().upper())
        if not student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Student with code '{code}' not found.",
            )
        return _student_response(student)

    students = student_service.list_students(db)
    return [_student_response(s) for s in students]


@router.get("/students/{student_id}/submissions/latest")
async def get_student_latest_submission(
    student_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_subscriber),
):
    student = student_service.get_student_by_id(db, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    submission = (
        db.query(AutograderSubmission)
        .filter(AutograderSubmission.student_id == student.id)
        .order_by(AutograderSubmission.version_number.desc())
        .first()
    )
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No submissions found for this student.",
        )
    return _submission_response(submission)


@router.get("/students/{student_id}/submissions")
async def get_student_submissions(
    student_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_subscriber),
):
    student = student_service.get_student_by_id(db, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    submissions = (
        db.query(AutograderSubmission)
        .filter(AutograderSubmission.student_id == student.id)
        .order_by(AutograderSubmission.version_number.desc())
        .all()
    )
    return [_submission_response(s) for s in submissions]


@router.get("/students/{student_id}")
async def get_student(
    student_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_subscriber),
):
    student = student_service.get_student_by_id(db, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    return _student_response(student)
