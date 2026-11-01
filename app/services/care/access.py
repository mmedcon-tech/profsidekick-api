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

import logging
from datetime import datetime
from typing import List, Optional, Set

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.database.models import (CareCourse, CareEntitlement, CareProgram, CareSupportGrant, Clinic, ClinicStaff,
                                 User)

logger = logging.getLogger(__name__)

# What a supporter may do. Patients implicitly hold every scope.
SUPPORT_SCOPES = ("education", "videos", "request_status")
ALL_SCOPES = SUPPORT_SCOPES + ("chat_history", "requests")

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
    def __init__(self, program: CareProgram, role: str, course_ids: Optional[Set],
                 scopes: Optional[List[str]] = None, grant: Optional[CareSupportGrant] = None):
        self.program = program
        self.role = role
        self.course_ids = course_ids  # None = every published course without its own entitlement gate
        self.scopes = list(scopes) if scopes is not None else list(ALL_SCOPES)
        self.grant = grant  # supporter only: the patient's grant this access rests on

    def has(self, scope: str) -> bool:
        return scope in self.scopes

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            # The program itself is visible to this user, so 403 does not leak anything.
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not included in the access you were given")

    def can_see_course(self, course: CareCourse) -> bool:
        if course.program_id != self.program.id or course.status != "published":
            return False
        if not course.requires_entitlement:
            return True
        return self.course_ids is not None and course.id in self.course_ids


class NotEnrolled(HTTPException):
    """403 for a signed-in user who is not enrolled in a publicly listed program.
    The detail carries only what the public catalog already shows."""

    def __init__(self, program: CareProgram):
        super().__init__(status.HTTP_403_FORBIDDEN, {
            "code": "not_enrolled", "message": "You are not enrolled in this program",
            "enrollment_policy": program.enrollment_policy})


def active_support_grant(db: DBSession, ent: CareEntitlement) -> Optional[CareSupportGrant]:
    now = datetime.utcnow()
    g = (db.query(CareSupportGrant)
         .filter(CareSupportGrant.entitlement_id == ent.id, CareSupportGrant.revoked_at.is_(None)).first())
    if not g or (g.expires_at and g.expires_at <= now):
        return None
    return g


def require_program_access(db: DBSession, user: User, program: CareProgram) -> ProgramAccess:
    """Entitled access, checked on every request.

    403/404 policy: unpublished or non-public programs answer 404 to anyone not
    entitled (the real reason is logged internally); a publicly listed program
    answers 403 `not_enrolled` so the client can show the enrollment screen.
    Supporter entitlements are only valid while the patient's grant is active."""
    if program.status != "published":
        logger.info("care.access denied user=%s program=%s reason=unpublished", user.id, program.id)
        raise not_found("Program not found")
    ents = active_entitlements(db, user, program)
    grant = None
    usable = []
    for e in ents:
        if e.care_role == "supporter":
            g = active_support_grant(db, e)
            if g is None:
                continue
            grant = g
        usable.append(e)
    if not usable:
        reason = "grant_inactive" if ents else "not_entitled"
        logger.info("care.access denied user=%s program=%s reason=%s", user.id, program.id, reason)
        if program.is_public:
            raise NotEnrolled(program)
        raise not_found("Program not found")
    course_ids = {e.course_id for e in usable if e.course_id}
    patient_like = [e for e in usable if e.care_role != "supporter"]
    if patient_like:
        role = next((e.care_role for e in patient_like if e.course_id is None), patient_like[0].care_role)
        return ProgramAccess(program, role, course_ids)
    return ProgramAccess(program, "supporter", course_ids, scopes=list(grant.scopes or []), grant=grant)
