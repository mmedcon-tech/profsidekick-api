import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database.connection import get_db
from app.database.models import Course, User
from app.schemas.schemas import (
    CourseDetails,
    CourseCreate,
    CourseUpdate,
    CourseEnrollment,
    CourseWithStudents,
    CourseStudent,
    CourseSessionSummary,
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
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    try:
        courses = await course_service.get_courses(db, current_user.id)
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
