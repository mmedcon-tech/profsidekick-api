"""Care platform phase-3 contracts (fertility demo / readiness work).

Context, enrollment invitations, supporter invitations + grants, clinical
requests (review queue), staff inbox, device assignments, TTS
reauthorization, health/admin status and client telemetry. Every route
re-derives access server-side from the path; nothing trusts client context.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import (CareDeviceAssignment, CareHandoff, CareInvitation, CareProgram, CareSupportGrant,
                                 Clinic, DoctorPersona, InstructionalVideo, User)
from app.dependencies.auth import get_current_user
from app.services.audit_service import record_audit_event
from app.services.care import access as acl
from app.services.care import chat, health, invites, review

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/care", tags=["care"])
TERMS_VERSION = "2026-11"
TTS_AUTH_TTL_S = 10 * 60
_client_events: Counter = Counter()


def _ctx(db, user, clinic_slug, program_slug):
    clinic = acl.get_clinic(db, clinic_slug)
    p = acl.get_program(db, clinic, program_slug)
    return clinic, acl.require_program_access(db, user, p)


def _rid(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


# ───────────── context ─────────────
@router.get("/p/{clinic_slug}/{program_slug}/context")
def context(clinic_slug: str, program_slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The server's view of who you are in this program. Clients render from this,
    never from cached client state, after a context switch."""
    clinic, a = _ctx(db, user, clinic_slug, program_slug)
    c = chat.get_or_create(db, user, a)
    persona = db.query(DoctorPersona).filter_by(id=a.program.persona_id).first() if a.program.persona_id else None
    return {"clinic": clinic.slug, "program": a.program.slug, "consultation_id": str(c.id), "care_role": a.role,
            "scopes": a.scopes, "is_demo": bool(a.program.is_demo or clinic.is_demo),
            "assistant": {"name": persona.name if persona else "Care assistant", "is_ai": True,
                          "disclosure": "AI guide with a sample identity, not a real clinician."
                          if (a.program.is_demo or clinic.is_demo) else "AI guide, not a clinician."},
            "device": chat.device_dict(chat.verified_device(db, user, a)),
            "environment": health.demo_environment()}


# ───────────── enrollment invitations (staff) ─────────────
class EnrollInviteBody(BaseModel):
    care_role: str = "patient"
    expires_in_days: int = Field(7, ge=1, le=invites.MAX_DAYS)
    max_uses: int = Field(1, ge=1, le=500)
    label: Optional[str] = Field(None, max_length=120)


def _staff_program(db, user, program_id, perm="can_manage") -> CareProgram:
    p = db.query(CareProgram).filter(CareProgram.id == program_id, CareProgram.clinic_ref_id.isnot(None)).first()
    if not p:
        raise acl.not_found()
    acl.require_staff(db, user, p.clinic_ref_id, perm)
    return p


@router.post("/studio/programs/{program_id}/invitations", status_code=201)
def create_enroll_invite(program_id: uuid.UUID, body: EnrollInviteBody, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    p = _staff_program(db, user, program_id)
    return invites.create_enrollment(db, user, p, body.care_role, body.expires_in_days, body.max_uses, body.label)


@router.get("/studio/programs/{program_id}/invitations")
def list_enroll_invites(program_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _staff_program(db, user, program_id)
    rows = (db.query(CareInvitation).filter_by(program_id=p.id, kind="enrollment")
            .order_by(CareInvitation.created_at.desc()).limit(200).all())
    return {"invitations": [invites.invite_dict(i) for i in rows]}


@router.delete("/studio/invitations/{invite_id}")
def revoke_enroll_invite(invite_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    i = db.query(CareInvitation).filter_by(id=invite_id, kind="enrollment").first()
    if not i:
        raise acl.not_found()
    acl.require_staff(db, user, i.clinic_id, "can_manage")
    return invites.revoke_invite(db, user, i)


class RedeemBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=40)
    terms_version: str


@router.post("/invitations/redeem")
def redeem(body: RedeemBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Returns only clinic + program slugs for the client to navigate to."""
    return invites.redeem(db, user, body.code, body.terms_version, TERMS_VERSION)


# ───────────── supporter invitations + grants (patient) ─────────────
class SupportInviteBody(BaseModel):
    scopes: List[str]
    expires_in_days: int = Field(7, ge=1, le=invites.MAX_DAYS)
    label: Optional[str] = Field(None, max_length=120)


@router.post("/p/{clinic_slug}/{program_slug}/support-invitations", status_code=201)
def create_support_invite(clinic_slug: str, program_slug: str, body: SupportInviteBody, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    _, a = _ctx(db, user, clinic_slug, program_slug)
    return invites.create_support(db, user, a, body.scopes, body.expires_in_days, body.label)


@router.get("/p/{clinic_slug}/{program_slug}/support")
def list_support(clinic_slug: str, program_slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, a = _ctx(db, user, clinic_slug, program_slug)
    if a.role != "patient":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the patient manages supporters")
    inv = (db.query(CareInvitation).filter_by(program_id=a.program.id, kind="support", patient_user_id=user.id)
           .order_by(CareInvitation.created_at.desc()).all())
    grants = (db.query(CareSupportGrant).filter_by(program_id=a.program.id, patient_user_id=user.id)
              .order_by(CareSupportGrant.created_at.desc()).all())
    return {"invitations": [invites.invite_dict(i) for i in inv], "grants": [invites.grant_dict(db, g) for g in grants],
            "available_scopes": list(acl.SUPPORT_SCOPES)}


@router.delete("/p/{clinic_slug}/{program_slug}/support-invitations/{invite_id}")
def revoke_support_invite(clinic_slug: str, program_slug: str, invite_id: uuid.UUID, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    _, a = _ctx(db, user, clinic_slug, program_slug)
    i = db.query(CareInvitation).filter_by(id=invite_id, kind="support", patient_user_id=user.id,
                                           program_id=a.program.id).first()
    if not i:
        raise acl.not_found()
    return invites.revoke_invite(db, user, i)


@router.delete("/p/{clinic_slug}/{program_slug}/support-grants/{grant_id}")
def revoke_support_grant(clinic_slug: str, program_slug: str, grant_id: uuid.UUID, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    _, a = _ctx(db, user, clinic_slug, program_slug)
    g = db.query(CareSupportGrant).filter_by(id=grant_id, program_id=a.program.id).first()
    if not g:
        raise acl.not_found()
    return invites.revoke_grant(db, user, g)


# ───────────── clinical requests (patient) ─────────────
class RequestBody(BaseModel):
    reason: str = "patient_request"
    summary: str = Field(..., min_length=1, max_length=2000)


@router.post("/p/{clinic_slug}/{program_slug}/requests")
def create_request(clinic_slug: str, program_slug: str, body: RequestBody, request: Request, response: Response,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    clinic, a = _ctx(db, user, clinic_slug, program_slug)
    c = chat.get_or_create(db, user, a)
    view, created = review.create(db, user, clinic, a, c.id, body.reason, body.summary,
                                  request.headers.get("idempotency-key"))
    response.status_code = 201 if created else 200
    return view


@router.get("/p/{clinic_slug}/{program_slug}/requests")
def list_requests(clinic_slug: str, program_slug: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    clinic, a = _ctx(db, user, clinic_slug, program_slug)
    if a.role == "supporter":
        a.require("request_status")
        rows = (db.query(CareHandoff).filter_by(program_id=a.program.id, user_id=a.grant.patient_user_id)
                .order_by(CareHandoff.created_at.desc()).limit(50).all())
        return {"requests": [review.supporter_view(db, h) for h in rows], "view": "status_only"}
    rows = (db.query(CareHandoff).filter_by(program_id=a.program.id, user_id=user.id)
            .order_by(CareHandoff.created_at.desc()).limit(50).all())
    return {"requests": [review.patient_view(db, h, clinic) for h in rows], "view": "full"}


# ───────────── staff inbox ─────────────
@router.get("/studio/clinics/{clinic_id}/inbox")
def staff_inbox(clinic_id: uuid.UUID, state: Optional[str] = None, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    return {"requests": review.inbox(db, user, clinic_id, state)}


class StaffActionBody(BaseModel):
    body: Optional[str] = Field(None, max_length=4000)
    assignee_id: Optional[uuid.UUID] = None


@router.post("/studio/requests/{request_id}/{action}")
def staff_request_action(request_id: uuid.UUID, action: Literal["assign", "acknowledge", "reply", "close"],
                         body: StaffActionBody = StaffActionBody(), db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    h = db.query(CareHandoff).filter_by(id=request_id).first()
    if not h:
        raise acl.not_found()
    return review.staff_action(db, user, h, action, body.body, body.assignee_id)


# ───────────── device assignments (staff) ─────────────
class DeviceBody(BaseModel):
    medication: str = Field(..., min_length=2, max_length=120)
    device: Optional[str] = Field(None, max_length=120)
    verified_by: str = Field(..., min_length=2, max_length=255)
    username: Optional[str] = None  # None → program-wide clinic configuration
    guide_lineage_id: Optional[uuid.UUID] = None
    video_id: Optional[uuid.UUID] = None


def device_row(d: CareDeviceAssignment) -> Dict[str, Any]:
    return {"id": str(d.id), **chat.device_dict(d), "user_id": str(d.user_id) if d.user_id else None,
            "revoked_at": d.revoked_at.isoformat() + "Z" if d.revoked_at else None}


@router.post("/studio/programs/{program_id}/device-assignments", status_code=201)
def create_device(program_id: uuid.UUID, body: DeviceBody, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    p = _staff_program(db, user, program_id, "can_approve")
    uid = None
    if body.username:
        u = db.query(User).filter_by(username=body.username).first()
        if not u or not acl.active_entitlements(db, u, p):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That person is not enrolled in this program")
        uid = u.id
    if body.video_id and not db.query(InstructionalVideo).filter_by(id=body.video_id, program_id=p.id).first():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Video is not in this program")
    d = CareDeviceAssignment(id=uuid.uuid4(), clinic_id=p.clinic_ref_id, program_id=p.id, user_id=uid,
                             medication=body.medication.strip(), device=(body.device or "").strip() or None,
                             guide_lineage_id=body.guide_lineage_id, video_id=body.video_id,
                             verified_by=body.verified_by.strip(), source="assignment" if uid else "clinic_config",
                             is_demo=bool(p.is_demo), created_at=datetime.utcnow())
    db.add(d)
    record_audit_event(db, action="care.device_assigned", entity_type="care_device_assignment", entity_id=d.id,
                       actor_user_id=user.id, data={"program_id": str(p.id), "scope": d.source})
    db.commit()
    return device_row(d)


@router.get("/studio/programs/{program_id}/device-assignments")
def list_devices(program_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _staff_program(db, user, program_id, "can_publish")
    rows = db.query(CareDeviceAssignment).filter_by(program_id=p.id).order_by(CareDeviceAssignment.created_at.desc()).all()
    return {"assignments": [device_row(d) for d in rows]}


@router.delete("/studio/device-assignments/{assignment_id}")
def revoke_device(assignment_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.query(CareDeviceAssignment).filter_by(id=assignment_id).first()
    if not d:
        raise acl.not_found()
    acl.require_staff(db, user, d.clinic_id, "can_approve")
    d.revoked_at = d.revoked_at or datetime.utcnow()
    db.commit()
    return device_row(d)


# ───────────── TTS reauthorization ─────────────
@router.post("/p/{clinic_slug}/{program_slug}/tts-authorization")
async def tts_authorization(clinic_slug: str, program_slug: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """Re-checked on every program switch and after a TTS 401: confirms the
    caller may still use voice here and returns the clinic-configured voice.
    The voice is chosen server-side; the client never picks another clinic's."""
    clinic, a = _ctx(db, user, clinic_slug, program_slug)
    a.require("education")
    persona = db.query(DoctorPersona).filter_by(id=a.program.persona_id).first() if a.program.persona_id else None
    return {"clinic": clinic.slug, "program": a.program.slug, "voice_id": persona.voice_id if persona else None,
            "gender": (persona.gender if persona and persona.gender in ("male", "female") else "female"),
            "liveavatar_avatar_id": persona.liveavatar_avatar_id if persona else None,
            "authorized_until": int(time.time()) + TTS_AUTH_TTL_S,
            "tts": (va := await health.voice_available(clinic))["available"], "tts_reason": va["reason"]}


# ───────────── health / admin status / client telemetry ─────────────
@router.get("/health")
async def care_health(request: Request):
    """Public and sanitized: per-dependency ok + error kind only (no live calls)."""
    rid = _rid(request)
    checks = [await health.check_llm(live=False, request_id=rid), await health.check_tts(live=False, request_id=rid),
              health.check_liveavatar(rid)]
    return {"request_id": rid, "environment": health.demo_environment(),
            "checks": [{"service": c["service"], "ok": c["ok"], "error_kind": c["error_kind"]} for c in checks]}


@router.get("/admin/status")
async def admin_status(request: Request, live: bool = False, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    acl.require_admin(user)
    rid = _rid(request)
    from sqlalchemy import text

    try:
        rev = db.execute(text("select version_num from alembic_version")).scalar()
    except Exception:  # noqa: BLE001 — e.g. test DBs built from metadata
        db.rollback()
        rev = None
    return {"request_id": rid, "environment": health.demo_environment(), "alembic_revision": rev,
            "checks": [await health.check_llm(live=live, request_id=rid), await health.check_tts(live=live, request_id=rid),
                       health.check_liveavatar(rid)],
            "client_events": dict(_client_events),
            "queue": {"open_requests": db.query(CareHandoff).filter(CareHandoff.status != "closed").count(),
                      "unassigned": db.query(CareHandoff).filter(CareHandoff.status != "closed",
                                                                 CareHandoff.assigned_to.is_(None)).count()}}


class ClientEvent(BaseModel):
    """Pilot instrumentation. Allowlisted enums only — no free text, no clinical content."""
    kind: Literal["playback_ok", "playback_failed", "autoplay_blocked", "tts_unavailable", "tts_unauthorized",
                  "avatar_started", "avatar_failed", "avatar_stopped", "context_switch", "stale_reply_dropped",
                  "chat_error", "handoff_created", "source_opened", "video_placeholder_shown"]
    result_type: Optional[Literal["education", "needs_clinician", "source_unavailable", "urgent_contact_path"]] = None
    request_id: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9-]{8,64}$")


@router.post("/telemetry/client-event", status_code=204)
def client_event(ev: ClientEvent, user: User = Depends(get_current_user)):
    _client_events[ev.kind] += 1
    if ev.result_type:
        _client_events[f"result:{ev.result_type}"] += 1
    logger.info("care.client_event kind=%s result=%s rid=%s", ev.kind, ev.result_type, ev.request_id)
    return Response(status_code=204)
