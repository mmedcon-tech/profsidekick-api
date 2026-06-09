import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database.connection import get_db
from app.database.models import Course, CourseAccessCode, User
from app.schemas.schemas import (
    CourseAccessCodeCreate,
    CourseAccessCodeResponse,
    CourseAccessCodesListResponse,
    CourseDetails,
    CourseCreate,
    CourseEnrollment,
    CourseJoinRequest,
    CourseJoinResponse,
    CourseSessionSummary,
    CourseStudent,
    CourseUpdate,
    CourseWithStudents,
)
from app.services.course_enrollment_service import (
    generate_course_code,
    get_codes_for_course,
    redeem_course_code,
    revoke_code,
)
from app.services.course_service import CourseService
from app.services.session_service import SessionService
from app.dependencies.auth import get_current_user

router = APIRouter(prefix="/api", tags=["courses"])

course_service = CourseService()
session_service = SessionService()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@router.get("/courses", response_model=List[CourseDetails])
async def get_courses(
    avatar_id: Optional[str] = Query(None, description="Filter to courses that have sessions using this avatar (subscriber marketplace use-case)."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        courses = await course_service.get_courses(db, current_user.id, avatar_id=avatar_id)
        return courses
    except HTTPException:
        raise  # pass 403 / 404 through unchanged so the message is readable
    except Exception as e:
        logger.error(f"❌ Error getting courses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error getting courses",
        )


@router.post("/courses", response_model=CourseDetails)
async def create_course(
    course_data: CourseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        course_data.user_id = current_user.id
        course = await course_service.create_course(db, course_data)
        return course
    except Exception as e:
        logger.error(f"❌ Error creating course: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creating course",
        )


@router.get("/courses/{course_id}", response_model=CourseDetails)
async def get_course(
    course_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        course = await course_service.get_course(db, course_id, current_user.id)
        return course
    except Exception as e:
        logger.error(f"❌ Error getting course: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error getting course",
        )


@router.put("/courses/{course_id}", response_model=CourseDetails)
async def update_course(
    course_id: str,
    course_data: CourseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        course_data.user_id = current_user.id
        course = await course_service.update_course(db, course_id, course_data)
        return course
    except Exception as e:
        logger.error(f"❌ Error updating course: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error updating course",
        )


@router.delete("/courses/{course_id}", response_model=CourseDetails)
async def delete_course(
    course_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        course = await course_service.delete_course(db, course_id, current_user.id)
        return course
    except Exception as e:
        logger.error(f"❌ Error deleting course: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error deleting course",
        )


@router.post("/courses/{course_id}/enroll", response_model=CourseDetails)
async def enroll_student(
    course_id: str,
    enrollment_data: CourseEnrollment,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        course = await course_service.enroll_course(
            db, course_id, current_user.id, enrollment_data.email
        )
        return course
    except Exception as e:
        logger.error(f"❌ Error enrolling student in course: {e}")
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/courses/{course_id}/students", response_model=List[CourseStudent])
async def get_course_students(
    course_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        students = await course_service.get_course_students(
            db, course_id, current_user.id
        )
        return students
    except Exception as e:
        logger.error(f"❌ Error getting course students: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error getting course students",
        )


@router.delete("/courses/{course_id}/students/{student_id}")
async def remove_student_from_course(
    course_id: str,
    student_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        await course_service.remove_student_from_course(
            db, course_id, student_id, current_user.id
        )
        return {"message": "Student removed from course successfully"}
    except Exception as e:
        logger.error(f"❌ Error removing student from course: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error removing student from course",
        )


@router.get("/courses/{course_id}/sessions", response_model=List[CourseSessionSummary])
async def get_course_sessions(
    course_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        sessions = await course_service.get_course_sessions(
            db, course_id, current_user.id
        )
        return sessions
    except HTTPException:
        raise  # pass 403/404 through with their real status codes and messages
    except Exception as e:
        logger.error(f"❌ Error getting course sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error getting course sessions",
        )


# ── Course Access Codes ──────────────────────────────────────────────────────

@router.post(
    "/courses/{course_id}/access-codes",
    response_model=CourseAccessCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_course_access_code(
    course_id: str,
    body: CourseAccessCodeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate an enrollment code for a course (publisher only, must own the course).
    """
    if current_user.role not in ("publisher", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Publishers only.")

    course = db.query(Course).filter(Course.course_id == course_id).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")
    if current_user.role != "admin" and str(course.user_id) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only manage codes for your own courses.")

    try:
        code = generate_course_code(
            db=db,
            course_id=course.id,
            created_by=current_user.id,
            max_uses=body.max_uses,
            expires_at=body.expires_at,
        )
        return code
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating course access code: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/courses/{course_id}/access-codes",
    response_model=CourseAccessCodesListResponse,
)
async def list_course_access_codes(
    course_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all access codes for a course (publisher/admin only)."""
    if current_user.role not in ("publisher", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Publishers only.")

    course = db.query(Course).filter(Course.course_id == course_id).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")

    try:
        codes = get_codes_for_course(db=db, course_id=course.id, caller_id=current_user.id)
        return CourseAccessCodesListResponse(codes=codes, total=len(codes))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error listing course access codes: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete(
    "/courses/access-codes/{code_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_course_access_code(
    code_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke (deactivate) a course access code (publisher/admin only)."""
    if current_user.role not in ("publisher", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Publishers only.")

    try:
        revoke_code(db=db, code_id=code_id, caller_id=current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error revoking course access code: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post(
    "/courses/join",
    response_model=CourseJoinResponse,
    status_code=status.HTTP_200_OK,
)
async def join_course(
    body: CourseJoinRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Subscriber redeems a course access code to enroll in a course.
    Idempotent: already-enrolled subscribers receive a success response.
    """
    if current_user.role not in ("subscriber", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only subscribers can join courses via access code.",
        )

    try:
        course = redeem_course_code(
            db=db,
            code_str=body.code,
            subscriber_id=current_user.id,
        )
        return CourseJoinResponse(
            course_id=course.course_id,
            course_name=course.name,
            message="Successfully enrolled in course.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error joining course: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
