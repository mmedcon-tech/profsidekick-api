"""Clinical review queue.

Lifecycle: received → assigned → acknowledged → replied → closed.
* Creation is idempotent per (user, Idempotency-Key).
* "received" is a receipt from the platform, never presented as a human
  acknowledgement; acknowledged_at is set only by a staff action.
* No assignee → the patient sees "Awaiting assignment".
* Staff replies are shown as written by a named person; in demo clinics they
  are flagged is_synthetic and labelled "synthetic demo activity".
* Staff alerts (alert_payload) carry ids only — never the question text.
* Nothing here promises 24/7 cover; the clinic's own response expectation is
  echoed instead.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.database.models import CareHandoff, CareHandoffEvent, CareProgram, Clinic, ClinicStaff, User
from app.services.audit_service import record_audit_event
from app.services.care import access as acl
from app.services.care import safety

logger = logging.getLogger(__name__)
REASONS = ("red_flag", "personal_judgment", "patient_request", "no_approved_source")
ACTIONS = ("assign", "acknowledge", "reply", "close")


def _iso(d):
    return d.isoformat() + "Z" if d else None


def _name(db, uid) -> Optional[str]:
    if not uid:
        return None
    u = db.query(User).filter_by(id=uid).first()
    return f"{u.first_name} {(u.last_name or '')[:1]}.".strip() if u else None


def _state(h: CareHandoff) -> str:
    return h.status if h.status in ("received", "assigned", "acknowledged", "replied", "closed") else "received"


def alert_payload(h: CareHandoff, clinic: Clinic) -> Dict[str, Any]:
    """What a staff notification may contain. Deliberately no summary, reason or patient name."""
    return {"type": "care_review_request", "clinic": clinic.slug, "request_id": str(h.id),
            "text": "A new request is waiting in the review queue."}


def _events(db, h: CareHandoff, include_bodies: bool) -> List[Dict[str, Any]]:
    out = []
    for e in (db.query(CareHandoffEvent).filter_by(handoff_id=h.id).order_by(CareHandoffEvent.created_at).all()):
        d = {"kind": e.kind, "at": _iso(e.created_at), "by": _name(db, e.actor_user_id) if e.kind != "received" else "System",
             "is_synthetic": e.is_synthetic,
             # replies are typed by a person on the clinic's staff, never generated
             "author_type": "system" if e.kind == "received" else "human_staff"}
        if include_bodies and e.body:
            d["body"] = e.body
        out.append(d)
    return out


def patient_view(db, h: CareHandoff, clinic: Clinic) -> Dict[str, Any]:
    return {
        "id": str(h.id), "status": _state(h), "reason": h.reason, "summary": h.summary,
        "received_at": _iso(h.received_at or h.created_at), "acknowledged_at": _iso(h.acknowledged_at),
        "assignee": _name(db, h.assigned_to) or "Awaiting assignment", "closed_at": _iso(h.closed_at),
        "simulated": h.simulated, "response_expectation": safety._expectation(clinic),
        "events": _events(db, h, include_bodies=True),
        "note": ("Simulated for this clinic. No message reached a real care team. Any staff activity shown is simulated."
                 if h.simulated else "Received by the platform. A person has not necessarily seen it yet."),
    }


def supporter_view(db, h: CareHandoff) -> Dict[str, Any]:
    """request_status scope: status only — no question text, no replies."""
    return {"id": str(h.id), "status": _state(h), "received_at": _iso(h.received_at or h.created_at),
            "assignee": "Assigned" if h.assigned_to else "Awaiting assignment", "closed_at": _iso(h.closed_at)}


def staff_view(db, h: CareHandoff) -> Dict[str, Any]:
    p = db.query(CareProgram).filter_by(id=h.program_id).first()
    return {**patient_view(db, h, db.query(Clinic).filter_by(id=h.clinic_id).first()),
            "program": p.slug if p else None, "patient": _name(db, h.user_id),
            "assigned_to": str(h.assigned_to) if h.assigned_to else None}


def _event(db, h, kind, actor_id, body=None, synthetic=False):
    db.add(CareHandoffEvent(id=uuid.uuid4(), handoff_id=h.id, actor_user_id=actor_id, kind=kind, body=body,
                            is_synthetic=synthetic, created_at=datetime.utcnow()))


def create(db: DBSession, user: User, clinic: Clinic, a: acl.ProgramAccess, consultation_id, reason: str,
           summary: str, idempotency_key: Optional[str]):
    if reason not in REASONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown reason")
    a.require("requests")
    key = (idempotency_key or "").strip()[:80] or None
    if key:
        prior = db.query(CareHandoff).filter_by(user_id=user.id, idempotency_key=key).first()
        if prior:
            if prior.program_id != a.program.id:
                raise HTTPException(status.HTTP_409_CONFLICT, "Idempotency-Key reused for a different program")
            return patient_view(db, prior, clinic), False
    # Same open question already queued (e.g. filed automatically by the chat, then the
    # patient also pressed "Ask my care team"): return it instead of a second case.
    norm = " ".join((summary or "").lower().split())[:2000]
    if norm:
        for prior in (db.query(CareHandoff).filter(CareHandoff.user_id == user.id, CareHandoff.program_id == a.program.id,
                                                   CareHandoff.status != "closed")
                      .order_by(CareHandoff.created_at.desc()).limit(50).all()):
            if " ".join((prior.summary or "").lower().split()) == norm:
                return patient_view(db, prior, clinic), False
    now = datetime.utcnow()
    h = CareHandoff(id=uuid.uuid4(), clinic_id=clinic.id, program_id=a.program.id, user_id=user.id,
                    consultation_id=consultation_id, reason=reason, summary=(summary or "")[:2000],
                    contact_route="routine", status="received", simulated=bool(clinic.is_demo),
                    idempotency_key=key, received_at=now, created_at=now, updated_at=now)
    db.add(h)
    try:
        db.flush()
    except IntegrityError:  # concurrent duplicate
        db.rollback()
        prior = db.query(CareHandoff).filter_by(user_id=user.id, idempotency_key=key).first()
        return patient_view(db, prior, clinic), False
    _event(db, h, "received", None)
    record_audit_event(db, action="care.request_received", entity_type="care_handoff", entity_id=h.id,
                       actor_user_id=user.id, data={"reason": reason, "simulated": h.simulated})
    logger.info("care.alert %s", alert_payload(h, clinic))
    db.commit()
    return patient_view(db, h, clinic), True


def staff_action(db: DBSession, actor: User, h: CareHandoff, action: str, body: Optional[str] = None,
                 assignee_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    if action not in ACTIONS:
        raise acl.not_found()
    acl.require_staff(db, actor, h.clinic_id, "can_view_clinical")
    if h.status == "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Request is closed")
    clinic = db.query(Clinic).filter_by(id=h.clinic_id).first()
    now = datetime.utcnow()
    if action == "assign":
        target = assignee_id or actor.id
        row = db.query(ClinicStaff).filter_by(clinic_id=h.clinic_id, user_id=target).first()
        if not row or not row.can_view_clinical:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Assignee must be clinical staff of this clinic")
        h.assigned_to = target
        if h.status == "received":
            h.status = "assigned"
    elif action == "acknowledge":
        if not h.assigned_to:
            h.assigned_to = actor.id
        h.acknowledged_at = h.acknowledged_at or now
        if h.status in ("received", "assigned"):
            h.status = "acknowledged"
    elif action == "reply":
        body = (body or "").strip()
        if not body:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Reply is empty")
        h.assigned_to = h.assigned_to or actor.id
        h.acknowledged_at = h.acknowledged_at or now
        h.status = "replied"
    elif action == "close":
        h.closed_at = now
        h.status = "closed"
    h.updated_at = now
    _event(db, h, action, actor.id, body=body[:4000] if action == "reply" else None,
           synthetic=bool(clinic and clinic.is_demo))
    record_audit_event(db, action=f"care.request_{action}", entity_type="care_handoff", entity_id=h.id,
                       actor_user_id=actor.id, data={"status": h.status})
    db.commit()
    return staff_view(db, h)


def inbox(db: DBSession, actor: User, clinic_id, state: Optional[str] = None) -> List[Dict[str, Any]]:
    acl.require_staff(db, actor, clinic_id, "can_view_clinical")
    q = db.query(CareHandoff).filter_by(clinic_id=clinic_id)
    if state == "open":
        q = q.filter(CareHandoff.status != "closed")
    elif state:
        q = q.filter_by(status=state)
    return [staff_view(db, h) for h in q.order_by(CareHandoff.created_at.desc()).limit(200).all()]
