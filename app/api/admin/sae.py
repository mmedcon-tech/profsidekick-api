"""
Admin-only SAE read endpoints.

GET /api/admin/sae/assessments  → all assessments across all publishers (no grading data)
GET /api/admin/sae/students     → all students, optionally filtered by assessment_id (no grading data)
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import SAEAssessment, SAEStudent, User
from app.dependencies.auth import require_admin
from app.schemas.sae import SAEAdminAssessmentRow, SAEAdminStudentRow

router = APIRouter(prefix="/api/admin/sae", tags=["admin-sae"])


@router.get("/assessments", response_model=list[SAEAdminAssessmentRow])
def list_admin_assessments(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    rows = (
        db.query(SAEAssessment, func.count(SAEStudent.id).label("enrolled_count"))
        .outerjoin(SAEStudent, SAEStudent.assessment_id == SAEAssessment.id)
        .group_by(SAEAssessment.id)
        .order_by(SAEAssessment.created_at.desc())
        .all()
    )
    return [
        SAEAdminAssessmentRow(
            id=assessment.id,
            name=assessment.name,
            description=assessment.description,
            created_at=assessment.created_at,
            publisher_id=assessment.publisher_id,
            publisher_username=assessment.publisher.username,
            enrolled_count=enrolled_count,
        )
        for assessment, enrolled_count in rows
    ]


@router.get("/students", response_model=list[SAEAdminStudentRow])
def list_admin_students(
    assessment_id: Optional[UUID] = Query(None, description="Filter to a single assessment"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(SAEStudent)
    if assessment_id is not None:
        query = query.filter(SAEStudent.assessment_id == assessment_id)
    students = query.order_by(SAEStudent.created_at.desc()).all()
    return [
        SAEAdminStudentRow(
            id=s.id,
            student_code=s.student_code,
            is_activated=s.is_activated,
            activation_date=s.activated_at,
            submission_count=s.submission_count,
            created_at=s.created_at,
            assessment_id=s.assessment_id,
            assessment_name=s.assessment.name,
            publisher_username=s.publisher.username,
            user_username=s.user.username if s.user else None,
        )
        for s in students
    ]
