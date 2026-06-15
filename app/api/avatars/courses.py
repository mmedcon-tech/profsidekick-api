"""W3: Publisher management of avatar–course links (R50)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Avatar, Course, User
from app.database.models.avatar_courses import AvatarCourse
from app.dependencies.auth import require_publisher
from app.schemas.schemas import (
    AvatarCourseAddRequest,
    AvatarCourseResponse,
    AvatarCoursesListResponse,
)

router = APIRouter(
    prefix="/api/publisher/avatars/{avatar_id}/courses",
    tags=["avatar-courses"],
)


def _get_avatar_and_assert_ownership(avatar_id: UUID, current_user: User, db: Session) -> Avatar:
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found"
        )
    if current_user.role != "admin" and str(avatar.publisher_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this avatar"
        )
    return avatar


@router.get("", response_model=AvatarCoursesListResponse)
def list_avatar_courses(
    avatar_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    """List all courses linked to an avatar."""
    _get_avatar_and_assert_ownership(avatar_id, current_user, db)
    links = (
        db.query(AvatarCourse)
        .filter(AvatarCourse.avatar_id == avatar_id)
        .order_by(AvatarCourse.sort_order, AvatarCourse.added_at)
        .all()
    )
    return AvatarCoursesListResponse(
        courses=[AvatarCourseResponse.model_validate(lnk) for lnk in links],
        total=len(links),
    )


@router.post("", response_model=AvatarCourseResponse, status_code=status.HTTP_201_CREATED)
def add_course_to_avatar(
    avatar_id: UUID,
    body: AvatarCourseAddRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    """Link a course to an avatar. Subscribers who subscribe to this avatar
    will be auto-enrolled in the course (R51, R57)."""
    _get_avatar_and_assert_ownership(avatar_id, current_user, db)

    course = db.query(Course).filter(Course.id == body.course_id).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )

    existing = (
        db.query(AvatarCourse)
        .filter(
            AvatarCourse.avatar_id == avatar_id,
            AvatarCourse.course_id == body.course_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Course is already linked to this avatar",
        )

    link = AvatarCourse(
        avatar_id=avatar_id,
        course_id=body.course_id,
        sort_order=body.sort_order,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return AvatarCourseResponse.model_validate(link)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_course_from_avatar(
    avatar_id: UUID,
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    """Unlink a course from an avatar.
    Existing subscriber enrollments in the course are NOT revoked."""
    _get_avatar_and_assert_ownership(avatar_id, current_user, db)

    link = (
        db.query(AvatarCourse)
        .filter(
            AvatarCourse.avatar_id == avatar_id,
            AvatarCourse.course_id == course_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course is not linked to this avatar",
        )

    db.delete(link)
    db.commit()
