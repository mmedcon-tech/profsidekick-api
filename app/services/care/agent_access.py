"""Part 4: Patient Care Memory, Doctor Guidance Profile and scoped, read-only agent access.

Every agent call re-checks, in this order: token -> grant exists -> not revoked -> not expired ->
scope -> patient still enrolled at the grant's clinic. Identity, patient and clinic come only from
the grant, never from the caller's arguments. Every call (allowed or denied) is written to a
patient-visible access log without content. Revocation therefore takes effect on the next call.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.database.models import (CareAgentAccessLog, CareAgentGrant, CareDoctorGuidance, CarePatientMemory,
                                 CareProgram, CareProgramMembership, Clinic, Consultation, ConsultationMessage, User)
from app.services.care import access as acl

# Preferences only. Clinical facts (doses, results, schedules) are never stored here.
MEMORY_KEYS = {"preferred_name": "What to call me", "language": "Language", "reading_level": "Explanation style",
               "communication_style": "How I like information", "contact_preference": "Preferred contact method",
               "accessibility": "Accessibility needs"}
_CLINICAL = re.compile(r"\b\d+(\.\d+)?\s*(mg|mcg|µg|iu|ml|units?)\b|\b(dose|dosage|inject\w*|mg)\b", re.I)
SCOPES = {"preferences": "get_my_preferences", "conversations": "list_my_conversations"}
TOOLS = {v: k for k, v in SCOPES.items()}
MAX_TTL_DAYS = 90
TOKEN_PREFIX = "myos_agt_"


def _now() -> datetime:
    return datetime.utcnow()


def enrolled_at(db: DBSession, user_id, clinic_id) -> bool:
    return db.query(CareProgramMembership).join(CareProgram, CareProgram.id == CareProgramMembership.program_id) \
        .filter(CareProgramMembership.user_id == user_id, CareProgram.clinic_ref_id == clinic_id).first() is not None


def patient_clinic(db: DBSession, user: User, clinic_slug: str) -> Clinic:
    clinic = acl.get_clinic(db, clinic_slug)
    if not enrolled_at(db, user.id, clinic.id):
        raise acl.not_found("Clinic not found")  # no hint that the clinic exists
    return clinic


# ── Patient Care Memory ──
def memory_list(db: DBSession, user: User, clinic: Clinic) -> List[Dict[str, Any]]:
    rows = db.query(CarePatientMemory).filter_by(clinic_id=clinic.id, user_id=user.id).order_by(CarePatientMemory.key).all()
    return [{"key": r.key, "label": MEMORY_KEYS.get(r.key, r.key), "value": r.value,
             "updated_at": (r.updated_at or r.created_at).isoformat() + "Z"} for r in rows]


def memory_set(db: DBSession, user: User, clinic: Clinic, key: str, value: str) -> List[Dict[str, Any]]:
    if key not in MEMORY_KEYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown preference")
    value = (value or "").strip()
    if not value or len(value) > 500:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Value must be 1-500 characters")
    if _CLINICAL.search(value):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Care Memory holds preferences only. Medication and dose details stay with your care team.")
    r = db.query(CarePatientMemory).filter_by(clinic_id=clinic.id, user_id=user.id, key=key).first()
    if r:
        r.value, r.updated_at = value, _now()
    else:
        db.add(CarePatientMemory(id=uuid.uuid4(), clinic_id=clinic.id, user_id=user.id, key=key, value=value,
                                 created_at=_now()))
    db.commit()
    return memory_list(db, user, clinic)


def memory_delete(db: DBSession, user: User, clinic: Clinic, key: str) -> List[Dict[str, Any]]:
    db.query(CarePatientMemory).filter_by(clinic_id=clinic.id, user_id=user.id, key=key).delete()
    db.commit()
    return memory_list(db, user, clinic)


# ── Doctor Guidance Profile ──
def guidance_get(db: DBSession, clinic_id, persona_id=None) -> Optional[str]:
    q = db.query(CareDoctorGuidance).filter_by(clinic_id=clinic_id, status="active")
    q = q.filter_by(persona_id=persona_id) if persona_id else q
    g = q.order_by(CareDoctorGuidance.updated_at.desc()).first()
    return g.text if g else None


def guidance_set(db: DBSession, actor: User, clinic_id, text: str, persona_id=None) -> Dict[str, Any]:
    acl.require_staff(db, actor, clinic_id, "can_approve")
    text = (text or "").strip()
    if not text or len(text) > 2000:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Guidance must be 1-2000 characters")
    for g in db.query(CareDoctorGuidance).filter_by(clinic_id=clinic_id, persona_id=persona_id, status="active").all():
        g.status = "superseded"
    g = CareDoctorGuidance(id=uuid.uuid4(), clinic_id=clinic_id, persona_id=persona_id, text=text, status="active",
                           updated_by=actor.id, updated_at=_now())
    db.add(g)
    db.commit()
    return {"text": g.text, "updated_at": g.updated_at.isoformat() + "Z"}


# ── Agent grants ──
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def grant_view(g: CareAgentGrant) -> Dict[str, Any]:
    now = _now()
    state = "revoked" if g.revoked_at else ("expired" if g.expires_at <= now else "active")
    return {"id": str(g.id), "agent_label": g.agent_label, "scopes": list(g.scopes or []), "state": state,
            "expires_at": g.expires_at.isoformat() + "Z", "created_at": g.created_at.isoformat() + "Z",
            "revoked_at": g.revoked_at.isoformat() + "Z" if g.revoked_at else None,
            "last_used_at": g.last_used_at.isoformat() + "Z" if g.last_used_at else None}


def grant_create(db: DBSession, user: User, clinic: Clinic, label: str, scopes: List[str], ttl_days: int) -> Dict[str, Any]:
    scopes = sorted(set(scopes or []))
    if not scopes or not set(scopes) <= set(SCOPES):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Scopes must be from {sorted(SCOPES)}")
    if not 1 <= int(ttl_days) <= MAX_TTL_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Expiry must be 1-{MAX_TTL_DAYS} days")
    label = (label or "").strip()[:120]
    if not label:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name the agent")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    g = CareAgentGrant(id=uuid.uuid4(), clinic_id=clinic.id, patient_user_id=user.id, agent_label=label, scopes=scopes,
                       token_sha256=_hash(token), expires_at=_now() + timedelta(days=int(ttl_days)), created_at=_now())
    db.add(g)
    db.commit()
    return {**grant_view(g), "token": token, "token_note": "Shown once. Store it in the agent; MYOS keeps only a hash."}


def grant_list(db: DBSession, user: User, clinic: Clinic) -> List[Dict[str, Any]]:
    rows = db.query(CareAgentGrant).filter_by(clinic_id=clinic.id, patient_user_id=user.id) \
        .order_by(CareAgentGrant.created_at.desc()).all()
    return [grant_view(g) for g in rows]


def grant_revoke(db: DBSession, user: User, clinic: Clinic, grant_id) -> Dict[str, Any]:
    g = db.query(CareAgentGrant).filter_by(id=grant_id, clinic_id=clinic.id, patient_user_id=user.id).first()
    if not g:
        raise acl.not_found("Grant not found")
    g.revoked_at = g.revoked_at or _now()
    db.commit()
    return grant_view(g)


def access_log(db: DBSession, user: User, clinic: Clinic, limit: int = 200) -> List[Dict[str, Any]]:
    rows = (db.query(CareAgentAccessLog, CareAgentGrant.agent_label)
            .outerjoin(CareAgentGrant, CareAgentGrant.id == CareAgentAccessLog.grant_id)
            .filter(CareAgentAccessLog.patient_user_id == user.id, CareAgentAccessLog.clinic_id == clinic.id)
            .order_by(CareAgentAccessLog.created_at.desc()).limit(limit).all())
    return [{"at": r.created_at.isoformat() + "Z", "agent": label, "tool": r.tool, "outcome": r.outcome,
             "reason": r.reason, "items": r.items} for r, label in rows]


@dataclass
class AgentContext:
    grant: CareAgentGrant
    patient_user_id: Any
    clinic_id: Any


def _log(db, tool, outcome, reason=None, g: Optional[CareAgentGrant] = None, items=None):
    db.add(CareAgentAccessLog(id=uuid.uuid4(), grant_id=g.id if g else None,
                              patient_user_id=g.patient_user_id if g else None, clinic_id=g.clinic_id if g else None,
                              tool=tool[:60], outcome=outcome, reason=reason, items=items, created_at=_now()))
    db.commit()


def authorize(db: DBSession, token: Optional[str], tool: str) -> AgentContext:
    """Per-call check. Raises 401/403 and logs a denial; never reveals whether another patient exists."""
    deny = HTTPException(status.HTTP_403_FORBIDDEN, "Agent access denied")
    if tool not in TOOLS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown tool")
    if not token or not token.startswith(TOKEN_PREFIX):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Agent token required")
    g = db.query(CareAgentGrant).filter_by(token_sha256=_hash(token)).first()
    if not g:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Agent token not recognised")
    reason = ("revoked" if g.revoked_at else "expired" if g.expires_at <= _now() else
              "scope_not_granted" if TOOLS[tool] not in (g.scopes or []) else
              "not_enrolled" if not enrolled_at(db, g.patient_user_id, g.clinic_id) else None)
    if reason:
        _log(db, tool, "denied", reason, g)
        raise deny
    g.last_used_at = _now()
    return AgentContext(g, g.patient_user_id, g.clinic_id)


def get_my_preferences(db: DBSession, token: Optional[str]) -> Dict[str, Any]:
    ctx = authorize(db, token, "get_my_preferences")
    rows = db.query(CarePatientMemory).filter_by(clinic_id=ctx.clinic_id, user_id=ctx.patient_user_id).all()
    out = {r.key: r.value for r in rows}
    _log(db, "get_my_preferences", "allowed", None, ctx.grant, len(out))
    return {"preferences": out}


def list_my_conversations(db: DBSession, token: Optional[str]) -> Dict[str, Any]:
    """Metadata only: program, start, last activity and message count. No message text."""
    from sqlalchemy import func

    ctx = authorize(db, token, "list_my_conversations")
    rows = (db.query(Consultation, CareProgram.name, CareProgram.slug, func.count(ConsultationMessage.id))
            .join(CareProgram, CareProgram.id == Consultation.program_id)
            .outerjoin(ConsultationMessage, ConsultationMessage.consultation_id == Consultation.id)
            .filter(Consultation.user_id == ctx.patient_user_id, CareProgram.clinic_ref_id == ctx.clinic_id)
            .group_by(Consultation.id, CareProgram.name, CareProgram.slug).all())
    out = [{"id": str(c.id), "program": slug, "program_name": name, "started_at": c.created_at.isoformat() + "Z",
            "last_activity_at": (c.last_activity_at or c.created_at).isoformat() + "Z", "messages": n}
           for c, name, slug, n in rows]
    _log(db, "list_my_conversations", "allowed", None, ctx.grant, len(out))
    return {"conversations": out}
