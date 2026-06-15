"""W2B: Programs system — publisher CRUD and subscriber browse endpoints."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import ProgramMembership, User
from app.dependencies.auth import get_current_user, require_publisher, require_subscriber
from app.schemas.schemas import (
    ProgramAddAvatarRequest,
    ProgramAddCourseRequest,
    ProgramAvatarResponse,
    ProgramCourseResponse,
    ProgramCreate,
    ProgramMembershipResponse,
    ProgramResponse,
    ProgramsListResponse,
    ProgramUpdate,
    SetUserProgramRequest,
)
from app.services import program_service

router = APIRouter(prefix="/api/programs", tags=["programs"])


# ── Publisher: program lifecycle ──────────────────────────────────────────────


@router.get("", response_model=ProgramsListResponse)
def list_programs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    publisher_id = None if current_user.role == "admin" else current_user.id
    programs = program_service.list_programs(db, publisher_id=publisher_id)
    return ProgramsListResponse(
        programs=[ProgramResponse.model_validate(p) for p in programs],
        total=len(programs),
    )


@router.post("", response_model=ProgramResponse, status_code=status.HTTP_201_CREATED)
def create_program(
    body: ProgramCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    p = program_service.create_program(
        name=body.name,
        publisher_id=current_user.id,
        db=db,
        description=body.description,
    )
    return ProgramResponse.model_validate(p)


@router.get("/my", response_model=ProgramsListResponse)
def subscriber_my_programs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_subscriber),
):
    programs = program_service.list_user_programs(current_user.id, db)
    return ProgramsListResponse(
        programs=[ProgramResponse.model_validate(p) for p in programs],
        total=len(programs),
    )


@router.get("/{program_id}", response_model=ProgramResponse)
def get_program(
    program_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_subscriber),
):
    p = program_service.get_program(program_id, db)
    return ProgramResponse.model_validate(p)


@router.patch("/{program_id}", response_model=ProgramResponse)
def update_program(
    program_id: UUID,
    body: ProgramUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    p = program_service.update_program(
        program_id=program_id,
        publisher_id=current_user.id,
        db=db,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
        requester_role=current_user.role,
    )
    return ProgramResponse.model_validate(p)


@router.delete("/{program_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_program(
    program_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    program_service.delete_program(
        program_id=program_id,
        publisher_id=current_user.id,
        db=db,
        requester_role=current_user.role,
    )


# ── Publisher: avatar membership ──────────────────────────────────────────────


@router.get("/{program_id}/avatars")
def list_program_avatars(
    program_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_subscriber),
):
    items = program_service.list_program_avatars(program_id, db)
    return {"avatars": [ProgramAvatarResponse.model_validate(i) for i in items], "total": len(items)}


@router.post("/{program_id}/avatars", response_model=ProgramAvatarResponse, status_code=status.HTTP_201_CREATED)
def add_avatar_to_program(
    program_id: UUID,
    body: ProgramAddAvatarRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    pa = program_service.add_avatar(
        program_id=program_id,
        avatar_id=body.avatar_id,
        publisher_id=current_user.id,
        db=db,
        requester_role=current_user.role,
    )
    return ProgramAvatarResponse.model_validate(pa)


@router.delete("/{program_id}/avatars/{avatar_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_avatar_from_program(
    program_id: UUID,
    avatar_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    program_service.remove_avatar(
        program_id=program_id,
        avatar_id=avatar_id,
        publisher_id=current_user.id,
        db=db,
        requester_role=current_user.role,
    )


# ── Publisher: course membership ──────────────────────────────────────────────


@router.get("/{program_id}/courses")
def list_program_courses(
    program_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_subscriber),
):
    items = program_service.list_program_courses(program_id, db)
    return {"courses": [ProgramCourseResponse.model_validate(i) for i in items], "total": len(items)}


@router.post("/{program_id}/courses", response_model=ProgramCourseResponse, status_code=status.HTTP_201_CREATED)
def add_course_to_program(
    program_id: UUID,
    body: ProgramAddCourseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    pc = program_service.add_course(
        program_id=program_id,
        course_id=body.course_id,
        publisher_id=current_user.id,
        db=db,
        requester_role=current_user.role,
    )
    return ProgramCourseResponse.model_validate(pc)


@router.delete("/{program_id}/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_course_from_program(
    program_id: UUID,
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    program_service.remove_course(
        program_id=program_id,
        course_id=course_id,
        publisher_id=current_user.id,
        db=db,
        requester_role=current_user.role,
    )


# ── Publisher: member list ────────────────────────────────────────────────────


@router.get("/{program_id}/members")
def list_program_members(
    program_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    members = program_service.list_members(program_id, db)
    return {
        "members": [ProgramMembershipResponse.model_validate(m) for m in members],
        "total": len(members),
    }
