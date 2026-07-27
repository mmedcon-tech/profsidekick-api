"""W2B: Business logic for the programs system."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import Avatar, Course, Program, ProgramAvatar, ProgramCourse, ProgramMembership, User


def get_program(program_id: UUID, db: Session) -> Program:
    p = db.query(Program).filter(Program.id == program_id).first()
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program not found")
    return p


def list_programs(db: Session, publisher_id: Optional[UUID] = None) -> list[Program]:
    q = db.query(Program).filter(Program.is_active.is_(True))
    if publisher_id:
        q = q.filter(Program.publisher_id == publisher_id)
    return q.order_by(Program.created_at.desc()).all()


def create_program(
    name: dict,
    slug: str,
    publisher_id: UUID,
    db: Session,
    description: Optional[dict] = None,
    theme_config: Optional[dict] = None,
    is_public: Optional[bool] = False,
) -> Program:
    p = Program(
        name=name,
        slug=slug,
        description=description,
        theme_config=theme_config,
        is_public=is_public,
        publisher_id=publisher_id
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def update_program(
    program_id: UUID,
    publisher_id: UUID,
    db: Session,
    name: Optional[dict] = None,
    slug: Optional[str] = None,
    description: Optional[dict] = None,
    theme_config: Optional[dict] = None,
    is_public: Optional[bool] = None,
    is_active: Optional[bool] = None,
    requester_role: str = "publisher",
) -> Program:
    p = get_program(program_id, db)
    _assert_ownership(p, publisher_id, requester_role)
    if name is not None:
        p.name = name
    if slug is not None:
        p.slug = slug
    if description is not None:
        p.description = description
    if theme_config is not None:
        p.theme_config = theme_config
    if is_public is not None:
        p.is_public = is_public
    if is_active is not None:
        p.is_active = is_active
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    return p


def delete_program(program_id: UUID, publisher_id: UUID, db: Session, requester_role: str = "publisher") -> None:
    p = get_program(program_id, db)
    _assert_ownership(p, publisher_id, requester_role)
    db.delete(p)
    db.commit()


# ── Avatar membership ────────────────────────────────────────────────────────


def list_program_avatars(program_id: UUID, db: Session) -> list[ProgramAvatar]:
    get_program(program_id, db)
    return db.query(ProgramAvatar).filter(ProgramAvatar.program_id == program_id).all()


def add_avatar(program_id: UUID, avatar_id: UUID, publisher_id: UUID, db: Session, requester_role: str = "publisher") -> ProgramAvatar:
    p = get_program(program_id, db)
    _assert_ownership(p, publisher_id, requester_role)

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    existing = db.query(ProgramAvatar).filter(
        ProgramAvatar.program_id == program_id, ProgramAvatar.avatar_id == avatar_id
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Avatar already in program")

    pa = ProgramAvatar(program_id=program_id, avatar_id=avatar_id)
    db.add(pa)
    db.commit()
    db.refresh(pa)
    return pa


def remove_avatar(program_id: UUID, avatar_id: UUID, publisher_id: UUID, db: Session, requester_role: str = "publisher") -> None:
    p = get_program(program_id, db)
    _assert_ownership(p, publisher_id, requester_role)

    pa = db.query(ProgramAvatar).filter(
        ProgramAvatar.program_id == program_id, ProgramAvatar.avatar_id == avatar_id
    ).first()
    if not pa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not in program")

    db.delete(pa)
    db.commit()


# ── Course membership ────────────────────────────────────────────────────────


def list_program_courses(program_id: UUID, db: Session) -> list[ProgramCourse]:
    get_program(program_id, db)
    return db.query(ProgramCourse).filter(ProgramCourse.program_id == program_id).all()


def add_course(program_id: UUID, course_id: UUID, publisher_id: UUID, db: Session, requester_role: str = "publisher") -> ProgramCourse:
    p = get_program(program_id, db)
    _assert_ownership(p, publisher_id, requester_role)

    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    existing = db.query(ProgramCourse).filter(
        ProgramCourse.program_id == program_id, ProgramCourse.course_id == course_id
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Course already in program")

    pc = ProgramCourse(program_id=program_id, course_id=course_id)
    db.add(pc)
    db.commit()
    db.refresh(pc)
    return pc


def remove_course(program_id: UUID, course_id: UUID, publisher_id: UUID, db: Session, requester_role: str = "publisher") -> None:
    p = get_program(program_id, db)
    _assert_ownership(p, publisher_id, requester_role)

    pc = db.query(ProgramCourse).filter(
        ProgramCourse.program_id == program_id, ProgramCourse.course_id == course_id
    ).first()
    if not pc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not in program")

    db.delete(pc)
    db.commit()


# ── User memberships ─────────────────────────────────────────────────────────


def list_members(program_id: UUID, db: Session) -> list[ProgramMembership]:
    get_program(program_id, db)
    return db.query(ProgramMembership).filter(ProgramMembership.program_id == program_id).all()


def list_user_programs(user_id: UUID, db: Session) -> list[Program]:
    return (
        db.query(Program)
        .join(ProgramMembership, ProgramMembership.program_id == Program.id)
        .filter(ProgramMembership.user_id == user_id, Program.is_active.is_(True))
        .order_by(Program.name)
        .all()
    )


def set_user_program(user: User, program_id: Optional[UUID], db: Session) -> User:
    if program_id is not None:
        p = db.query(Program).filter(Program.id == program_id, Program.is_active.is_(True)).first()
        if not p:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program not found")
        mem = db.query(ProgramMembership).filter(
            ProgramMembership.program_id == program_id,
            ProgramMembership.user_id == user.id,
        ).first()
        if not mem:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this program",
            )
    user.current_program_id = program_id
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


# ── Internal helpers ─────────────────────────────────────────────────────────


def _assert_ownership(program: Program, publisher_id: UUID, requester_role: str) -> None:
    if requester_role == "admin":
        return
    if str(program.publisher_id) != str(publisher_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this program",
        )
