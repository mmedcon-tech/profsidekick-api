"""Server-side tenant and role boundaries for the care platform.

* Platform admin (users.role == 'admin') orchestrates: templates, clinics,
  staff assignment, integration status. Admin does NOT get patient
  conversations or handoffs through this role.
* Clinic staff flags are separate: can_manage, can_publish (drafts,
  structure, publish/unpublish), can_approve (clinical approval),
  can_view_clinical (handoffs for that clinic only).
* Patients reach a program only through an active CareEntitlement for that
  clinic + program (optionally restricted to courses).
"""
from __future__ import annotations

from typing import Optional, Set

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.database.models import CareCourse, CareEntitlement, CareProgram, Clinic, ClinicStaff, User

PERMS = ("can_manage", "can_publish", "can_approve", "can_view_clinical")


def is_admin(user: User) -> bool:
    role = getattr(user.role, "value", user.role)
    return str(role) == "admin"


def not_found(what: str = "Not found") -> HTTPException:
    # 404 rather than 403 so other tenants' ids are not confirmed.
    return HTTPException(status.HTTP_404_NOT_FOUND, what)


def staff_row(db: DBSession, user: User, clinic_id) -> Optional[ClinicStaff]:
    return db.query(ClinicStaff).filter_by(clinic_id=clinic_id, user_id=user.id).first()


def require_staff(db: DBSession, user: User, clinic_id, perm: str) -> ClinicStaff:
    assert perm in PERMS
    row = staff_row(db, user, clinic_id)
    if not row:
        raise not_found("Clinic not found")
    if not getattr(row, perm):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing clinic permission: {perm}")
    return row


def require_admin(user: User) -> User:
    if not is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform admin only")
    return user


def get_clinic(db: DBSession, slug: str) -> Clinic:
    c = db.query(Clinic).filter_by(slug=slug, status="active").first()
    if not c:
        raise not_found("Clinic not found")
    return c


def get_program(db: DBSession, clinic: Clinic, slug: str) -> CareProgram:
    p = db.query(CareProgram).filter_by(clinic_ref_id=clinic.id, slug=slug).first()
    if not p:
        raise not_found("Program not found")
    return p


def active_entitlements(db: DBSession, user: User, program: CareProgram):
    return (db.query(CareEntitlement)
            .filter(CareEntitlement.user_id == user.id, CareEntitlement.program_id == program.id,
                    CareEntitlement.clinic_id == program.clinic_ref_id, CareEntitlement.revoked_at.is_(None))
            .all())


class ProgramAccess:
    def __init__(self, program: CareProgram, role: str, course_ids: Optional[Set]):
        self.program = program
        self.role = role
        self.course_ids = course_ids  # None = every published course without its own entitlement gate

    def can_see_course(self, course: CareCourse) -> bool:
        if course.program_id != self.program.id or course.status != "published":
            return False
        if not course.requires_entitlement:
            return True
        return self.course_ids is not None and course.id in self.course_ids


def require_program_access(db: DBSession, user: User, program: CareProgram) -> ProgramAccess:
    """Entitled patient access. Unpublished programs are invisible to patients."""
    if program.status != "published":
        raise not_found("Program not found")
    ents = active_entitlements(db, user, program)
    if not ents:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not enrolled in this program")
    course_ids = {e.course_id for e in ents if e.course_id}
    role = next((e.care_role for e in ents if e.course_id is None), ents[0].care_role)
    return ProgramAccess(program, role, course_ids)
