"""Enrollment codes and supporter invitations.

* Codes are random, shown once, stored only as SHA-256, expire, can be
  revoked, and have a use limit.
* A supporter invitation is created by the patient, is scoped (subset of
  access.SUPPORT_SCOPES), and must be redeemed by the supporter's OWN signed-in
  account. Redeeming creates a CareSupportGrant plus a `supporter` entitlement;
  access.require_program_access re-checks the grant on every request, so
  revocation or expiry takes effect immediately.
* Any invalid, expired, revoked or used-up code answers the same 404 so codes
  cannot be probed; the precise reason is logged.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.database.models import (CareEntitlement, CareInvitation, CareProgram, CareSupportGrant, Clinic, User)
from app.services.audit_service import record_audit_event
from app.services.care import access as acl

logger = logging.getLogger(__name__)
MAX_DAYS = 30
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def _hash(code: str) -> str:
    norm = "".join(ch for ch in (code or "").upper() if ch.isalnum())
    return hashlib.sha256(norm.encode()).hexdigest()


def _new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def invite_dict(i: CareInvitation, code: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.utcnow()
    state = ("revoked" if i.revoked_at else "expired" if i.expires_at <= now
             else "used" if i.use_count >= i.max_uses else "active")
    d = {"id": str(i.id), "kind": i.kind, "care_role": i.care_role, "scopes": i.scopes or [], "label": i.label,
         "code_hint": i.code_hint, "expires_at": i.expires_at.isoformat() + "Z", "max_uses": i.max_uses,
         "use_count": i.use_count, "state": state}
    if code:
        d["code"] = code  # returned exactly once, at creation
    return d


def _create(db, *, kind, clinic_id, program_id, care_role, scopes, label, actor, patient_id, days, max_uses):
    days = max(1, min(int(days or 7), MAX_DAYS))
    code = _new_code()
    i = CareInvitation(id=uuid.uuid4(), kind=kind, code_hash=_hash(code), code_hint=code[-4:], clinic_id=clinic_id,
                       program_id=program_id, care_role=care_role, scopes=scopes, label=(label or "")[:120] or None,
                       created_by=actor.id, patient_user_id=patient_id,
                       expires_at=datetime.utcnow() + timedelta(days=days), max_uses=max(1, min(int(max_uses or 1), 500)),
                       created_at=datetime.utcnow())
    db.add(i)
    record_audit_event(db, action=f"care.invite_created.{kind}", entity_type="care_invitation", entity_id=i.id,
                       actor_user_id=actor.id, data={"program_id": str(program_id), "scopes": scopes, "days": days})
    db.commit()
    return invite_dict(i, code)


def create_enrollment(db: DBSession, actor: User, program: CareProgram, care_role: str, days: int, max_uses: int,
                      label: Optional[str]) -> Dict[str, Any]:
    if care_role not in ("patient", "caregiver"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "care_role must be patient or caregiver")
    return _create(db, kind="enrollment", clinic_id=program.clinic_ref_id, program_id=program.id, care_role=care_role,
                   scopes=[], label=label, actor=actor, patient_id=None, days=days, max_uses=max_uses)


def create_support(db: DBSession, patient: User, a: acl.ProgramAccess, scopes: List[str], days: int,
                   label: Optional[str]) -> Dict[str, Any]:
    if a.role != "patient":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the patient can invite a supporter")
    scopes = sorted(set(scopes or []))
    if not scopes or any(s not in acl.SUPPORT_SCOPES for s in scopes):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"scopes must be a subset of {list(acl.SUPPORT_SCOPES)}")
    return _create(db, kind="support", clinic_id=a.program.clinic_ref_id, program_id=a.program.id,
                   care_role="supporter", scopes=scopes, label=label, actor=patient, patient_id=patient.id,
                   days=days, max_uses=1)


def _invalid(reason: str, i: Optional[CareInvitation] = None) -> HTTPException:
    logger.info("care.invite rejected reason=%s invite=%s", reason, i.id if i else None)
    return HTTPException(status.HTTP_404_NOT_FOUND, "This invitation code is not valid")


def redeem(db: DBSession, user: User, code: str, terms_version: str, current_terms: str) -> Dict[str, Any]:
    i = db.query(CareInvitation).filter_by(code_hash=_hash(code)).with_for_update().first()
    now = datetime.utcnow()
    if not i:
        raise _invalid("unknown")
    if i.revoked_at:
        raise _invalid("revoked", i)
    if i.expires_at <= now:
        raise _invalid("expired", i)
    p = db.query(CareProgram).filter_by(id=i.program_id).first()
    clinic = db.query(Clinic).filter_by(id=i.clinic_id).first()
    if not p or p.status != "published" or not clinic or clinic.status != "active":
        raise _invalid("program_unavailable", i)
    if terms_version != current_terms:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Please accept the current terms ({current_terms})")
    target = {"clinic": clinic.slug, "program": p.slug}
    if i.kind == "support":
        if i.patient_user_id == user.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "This invitation is for your supporter. They need to sign in with their own account.")
        existing = (db.query(CareSupportGrant).filter_by(invitation_id=i.id, supporter_user_id=user.id)
                    .filter(CareSupportGrant.revoked_at.is_(None)).first())
        if existing:
            return {**target, "role": "supporter", "already": True}
    elif any(e.care_role != "supporter" for e in acl.active_entitlements(db, user, p)):
        return {**target, "role": "patient", "already": True}
    if i.use_count >= i.max_uses:
        raise _invalid("used_up", i)
    ent = CareEntitlement(id=uuid.uuid4(), user_id=user.id, clinic_id=i.clinic_id, program_id=i.program_id,
                          care_role=i.care_role, source="support_invitation" if i.kind == "support" else "invite_code",
                          granted_by=i.created_by, terms_version=terms_version, created_at=now)
    db.add(ent)
    db.flush()
    if i.kind == "support":
        db.add(CareSupportGrant(id=uuid.uuid4(), clinic_id=i.clinic_id, program_id=i.program_id,
                                patient_user_id=i.patient_user_id, supporter_user_id=user.id, invitation_id=i.id,
                                entitlement_id=ent.id, scopes=i.scopes or [], created_at=now))
    i.use_count += 1
    record_audit_event(db, action=f"care.invite_redeemed.{i.kind}", entity_type="care_invitation", entity_id=i.id,
                       actor_user_id=user.id, data={"program_id": str(i.program_id)})
    db.commit()
    return {**target, "role": i.care_role, "already": False}


def revoke_invite(db: DBSession, actor: User, i: CareInvitation) -> Dict[str, Any]:
    if not i.revoked_at:
        i.revoked_at = datetime.utcnow()
        record_audit_event(db, action="care.invite_revoked", entity_type="care_invitation", entity_id=i.id,
                           actor_user_id=actor.id, data={})
        db.commit()
    return invite_dict(i)


def grant_dict(db, g: CareSupportGrant) -> Dict[str, Any]:
    sup = db.query(User).filter_by(id=g.supporter_user_id).first()
    return {"id": str(g.id), "supporter": (sup.first_name if sup and getattr(sup, "first_name", None) else
                                           (sup.username if sup else "")),
            "scopes": g.scopes or [], "created_at": g.created_at.isoformat() + "Z",
            "revoked_at": g.revoked_at.isoformat() + "Z" if g.revoked_at else None}


def revoke_grant(db: DBSession, patient: User, g: CareSupportGrant) -> Dict[str, Any]:
    if g.patient_user_id != patient.id:
        raise acl.not_found()
    if not g.revoked_at:
        now = datetime.utcnow()
        g.revoked_at = now
        ent = db.query(CareEntitlement).filter_by(id=g.entitlement_id).first() if g.entitlement_id else None
        if ent and not ent.revoked_at:
            ent.revoked_at = now
        record_audit_event(db, action="care.support_revoked", entity_type="care_support_grant", entity_id=g.id,
                           actor_user_id=patient.id, data={})
        db.commit()
    return grant_dict(db, g)
