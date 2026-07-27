"""
Course access-code enrollment service.

Responsibilities:
  - Generate publisher-owned enrollment codes for a course
  - Redeem a code → enroll the subscriber in course_students
  - List codes for a course (publisher-only, ownership verified)
  - Revoke a code (publisher-only)
"""

import random
import string
import uuid
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import Course, CourseAccessCode, CourseStudent, User


def _generate_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


def generate_course_code(
    db: Session,
    course_id: UUID,
    created_by: UUID,
    max_uses: Optional[int] = None,
    expires_at: Optional[datetime] = None,
) -> CourseAccessCode:
    """
    Create a new enrollment code for a course.
    The caller must be the course owner (verified before calling this function).
    """
    # collision-safe generation
    for _ in range(10):
        code_str = _generate_code()
        if not db.query(CourseAccessCode).filter_by(code=code_str).first():
            break
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate a unique access code. Please try again.",
        )

    code = CourseAccessCode(
        id=uuid.uuid4(),
        course_id=course_id,
        code=code_str,
        created_by=created_by,
        max_uses=max_uses,
        uses_count=0,
        is_active=True,
        expires_at=expires_at,
        created_at=datetime.utcnow(),
    )
    db.add(code)
    db.commit()
    db.refresh(code)
    return code


def redeem_course_code(
    db: Session,
    code_str: str,
    subscriber_id: UUID,
) -> Course:
    """
    Validate and redeem an enrollment code, enrolling the subscriber in the course.
    Returns the Course on success.
    """
    code_str = code_str.strip().upper()
    code = db.query(CourseAccessCode).filter_by(code=code_str).first()

    if not code or not code.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or inactive access code.",
        )
    if code.expires_at and code.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This access code has expired.",
        )
    if code.max_uses is not None and code.uses_count >= code.max_uses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This access code has reached its maximum uses.",
        )

    course = db.query(Course).filter_by(id=code.course_id).first()
    if not course or not course.is_active or course.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The course associated with this code is no longer available.",
        )

    # Idempotent: already enrolled is OK, just return the course
    existing = db.query(CourseStudent).filter_by(
        course_id=course.id,
        user_id=subscriber_id,
    ).first()
    if existing:
        return course

    enrollment = CourseStudent(
        id=uuid.uuid4(),
        course_id=course.id,
        user_id=subscriber_id,
        enrollment_date=datetime.utcnow(),
    )
    db.add(enrollment)

    code.uses_count += 1
    if code.max_uses is not None and code.uses_count >= code.max_uses:
        code.is_active = False

    db.commit()
    db.refresh(course)
    return course


def get_codes_for_course(
    db: Session,
    course_id: UUID,
    caller_id: UUID,
) -> List[CourseAccessCode]:
    """
    List all access codes for a course.
    Caller must own the course.
    """
    course = db.query(Course).filter_by(id=course_id).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")
    if str(course.user_id) != str(caller_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view codes for your own courses.",
        )

    return (
        db.query(CourseAccessCode)
        .filter_by(course_id=course_id)
        .order_by(CourseAccessCode.created_at.desc())
        .all()
    )


def revoke_code(
    db: Session,
    code_id: UUID,
    caller_id: UUID,
) -> CourseAccessCode:
    """
    Deactivate a course access code.
    Caller must own the course the code belongs to.
    """
    code = db.query(CourseAccessCode).filter_by(id=code_id).first()
    if not code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access code not found.")

    course = db.query(Course).filter_by(id=code.course_id).first()
    if not course or str(course.user_id) != str(caller_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only revoke codes for your own courses.",
        )

    code.is_active = False
    db.commit()
    db.refresh(code)
    return code
