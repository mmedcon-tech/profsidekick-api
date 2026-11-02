"""Care platform API.

/api/care/catalog, /api/care/preview/...   public previews (never private content)
/api/care/me/...  /api/care/p/{clinic}/{program}/...   entitled patients
/api/care/studio/...   clinic staff (publish / approve / manage are separate flags)
/api/care/admin/...    platform admin (templates, integration status)
Every query is scoped server-side by clinic + program (+ course).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database.connection import get_db
from app.database.models import (Avatar, CareContentItem, CareCourse, CareEntitlement, CareHandoff, CareLesson,
                                 CareProgram, Clinic, ClinicStaff, Consultation, ConsultationMessage, DoctorPersona,
                                 InstructionalVideo, ProgramTemplate, RedFlagRule, User)
from app.dependencies.auth import get_current_user
from app.services.audit_service import record_audit_event
from app.services.care import access as acl
from app.services.care import chat, content, review

router = APIRouter(prefix="/api/care", tags=["care"])

TERMS_VERSION = "2026-11"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,98}$")
MAX_VIDEO_BYTES = 500 * 1024 * 1024
PLAYBACK_TTL_S = 15 * 60
URGENCIES = ("emergency", "urgent", "same_day", "routine")


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    if not SLUG.match(s):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Use lowercase letters, digits and dashes for the slug")
    return s


def _iso(d):
    return d.isoformat() + "Z" if d else None


def _uuid(v) -> Optional[uuid.UUID]:
    if v in (None, ""):
        return None
    try:
        return uuid.UUID(str(v))
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid id")


def _date(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", ""))
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid date: {v}")


# ─────────────────────────── serializers ───────────────────────────
def clinic_dict(c: Clinic, full: bool = False) -> Dict[str, Any]:
    d = {"id": str(c.id), "slug": c.slug, "name": c.name, "description": c.description,
         "branding": c.branding or {}, "is_demo": c.is_demo, "is_pilot": bool(getattr(c, "is_pilot", False)),
         "languages": getattr(c, "languages", None) or ["en"]}
    if full:
        d.update(contact_routes=c.contact_routes or [], response_expectation=c.response_expectation, status=c.status)
    return d


def template_dict(t: ProgramTemplate) -> Dict[str, Any]:
    return {"id": str(t.id), "slug": t.slug, "name": t.name, "care_area": t.care_area,
            "description": t.description, "default_config": t.default_config or {}, "status": t.status}


def persona_dict(p: DoctorPersona, full: bool = False) -> Dict[str, Any]:
    d = {"id": str(p.id), "name": p.name, "title": p.title, "specialty": p.specialty, "is_demo": p.is_demo,
         "liveavatar_avatar_id": p.liveavatar_avatar_id, "variant": p.variant, "voice_id": p.voice_id,
         "gender": p.gender, "avatar_id": str(p.avatar_id) if p.avatar_id else None,
         "slug": p.slug, "photo": (p.profile or {}).get("photo"), "first_messages": p.first_messages or {},
         "modes": (p.profile or {}).get("modes") or ["text"], "reviewed_by": (p.profile or {}).get("reviewed_by")}
    if full:
        d.update(prompt=p.prompt, status=p.status, clinic_id=str(p.clinic_id))
    return d


def program_dict(db: Session, p: CareProgram, clinic: Clinic) -> Dict[str, Any]:
    t = db.query(ProgramTemplate).filter_by(id=p.template_id).first() if p.template_id else None
    persona = db.query(DoctorPersona).filter_by(id=p.persona_id).first() if p.persona_id else None
    return {"id": str(p.id), "slug": p.slug, "name": p.name, "description": p.description, "status": p.status,
            "enrollment_policy": p.enrollment_policy, "branding": {**(clinic.branding or {}), **(p.branding or {})},
            "position": p.position, "is_demo": p.is_demo or clinic.is_demo,
            "template": template_dict(t) if t else None, "persona": persona_dict(persona) if persona else None,
            "clinic": clinic_dict(clinic), "legacy": p.slug == "ivf-care" and clinic.slug == "demo-harbor"}


def course_dict(c: CareCourse, lessons=None) -> Dict[str, Any]:
    d = {"id": str(c.id), "slug": c.slug, "title": c.title, "description": c.description, "position": c.position,
         "status": c.status, "requires_entitlement": c.requires_entitlement}
    if lessons is not None:
        d["lessons"] = [{"id": str(l.id), "title": l.title, "body": l.body, "position": l.position,
                         "status": l.status} for l in lessons]
    return d


def video_dict(v: InstructionalVideo) -> Dict[str, Any]:
    return {"id": str(v.id), "title": v.title, "description": v.description, "language": v.language,
            "status": v.status, "course_id": str(v.course_id) if v.course_id else None,
            "lesson_id": str(v.lesson_id) if v.lesson_id else None, "position": v.position,
            "has_file": bool(v.storage_uri),
            "footage": "available" if (v.storage_uri or v.external_url) else "placeholder", "external_url": v.external_url, "has_captions": bool(v.captions_vtt),
            "has_transcript": bool(v.transcript), "has_thumbnail": bool(v.thumbnail_uri),
            "reviewer": v.reviewer, "approved_at": _iso(v.approved_at), "uploaded_at": _iso(v.created_at)}


def flag_dict(r: RedFlagRule) -> Dict[str, Any]:
    return {"id": str(r.id), "symptom": r.symptom, "match_terms": r.match_terms or [], "clinic_action": r.clinic_action,
            "urgency": r.urgency, "contact_route": r.contact_route, "applicability": r.applicability,
            "reviewer": r.reviewer, "review_date": _iso(r.review_date), "status": r.status, "is_demo": r.is_demo,
            "course_id": str(r.course_id) if r.course_id else None}


# ─────────────────────────── public ───────────────────────────
def _published(db: Session):
    return (db.query(CareProgram, Clinic).join(Clinic, Clinic.id == CareProgram.clinic_ref_id)
            .filter(CareProgram.status == "published", Clinic.status == "active"))


@router.get("/catalog")
def catalog(db: Session = Depends(get_db)):
    rows = _published(db).order_by(Clinic.name, CareProgram.position, CareProgram.name).all()
    return {"programs": [program_dict(db, p, c) for p, c in rows],
            "templates": [template_dict(t) for t in db.query(ProgramTemplate).filter_by(status="active")
                          .order_by(ProgramTemplate.name).all()]}


@router.get("/preview/{clinic_slug}/{program_slug}")
def preview(clinic_slug: str, program_slug: str, db: Session = Depends(get_db)):
    """Public preview: names and course outline only. No lesson bodies, content, videos or red flags."""
    clinic = acl.get_clinic(db, clinic_slug)
    p = acl.get_program(db, clinic, program_slug)
    if p.status != "published":
        raise acl.not_found("Program not found")
    courses = (db.query(CareCourse).filter_by(program_id=p.id, status="published")
               .order_by(CareCourse.position).all())
    return {"program": program_dict(db, p, clinic),
            "courses": [{"title": c.title, "description": c.description} for c in courses],
            "terms_version": TERMS_VERSION}


# ─────────────────────────── patient ───────────────────────────
@router.get("/me/programs")
def my_programs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(CareProgram, Clinic).join(Clinic, Clinic.id == CareProgram.clinic_ref_id)
            .join(CareEntitlement, CareEntitlement.program_id == CareProgram.id)
            .filter(CareEntitlement.user_id == user.id, CareEntitlement.revoked_at.is_(None),
                    CareEntitlement.clinic_id == Clinic.id, CareProgram.status == "published",
                    Clinic.status == "active")
            .order_by(Clinic.name, CareProgram.position).distinct().all())
    return {"programs": [program_dict(db, p, c) for p, c in rows]}


class EnrollBody(BaseModel):
    care_role: str = "patient"
    terms_version: str


@router.post("/p/{clinic_slug}/{program_slug}/enroll")
def enroll(clinic_slug: str, program_slug: str, body: EnrollBody, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    clinic = acl.get_clinic(db, clinic_slug)
    p = acl.get_program(db, clinic, program_slug)
    if p.status != "published":
        raise acl.not_found("Program not found")
    if p.enrollment_policy != "open":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This program is by clinic invitation. Ask your clinic to add you.")
    if body.terms_version != TERMS_VERSION:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Please accept the current terms ({TERMS_VERSION})")
    if body.care_role not in ("patient", "caregiver"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "care_role must be patient or caregiver")
    if not acl.active_entitlements(db, user, p):
        db.add(CareEntitlement(id=uuid.uuid4(), user_id=user.id, clinic_id=clinic.id, program_id=p.id,
                               care_role=body.care_role, source="open_enrollment", terms_version=TERMS_VERSION,
                               created_at=datetime.utcnow()))
        record_audit_event(db, action="care.enroll", entity_type="care_program", entity_id=p.id,
                           actor_user_id=user.id, data={"clinic": clinic.slug, "terms_version": TERMS_VERSION})
        db.commit()
    return {"ok": True, "clinic": clinic.slug, "program": p.slug}


def _ctx(db, user, clinic_slug, program_slug):
    clinic = acl.get_clinic(db, clinic_slug)
    p = acl.get_program(db, clinic, program_slug)
    return clinic, acl.require_program_access(db, user, p)


def _program_view(db: Session, clinic: Clinic, p: CareProgram, can_see_course, include_drafts=False):
    now = datetime.utcnow()
    courses = db.query(CareCourse).filter_by(program_id=p.id).order_by(CareCourse.position).all()
    courses = [c for c in courses if include_drafts or can_see_course(c)]
    ids = {c.id for c in courses}
    lesson_ok = (lambda l: True) if include_drafts else (lambda l: l.status == "published")
    out_courses = []
    for c in courses:
        ls = db.query(CareLesson).filter_by(course_id=c.id).order_by(CareLesson.position).all()
        out_courses.append(course_dict(c, [l for l in ls if lesson_ok(l)]))
    vq = db.query(InstructionalVideo).filter(InstructionalVideo.program_id == p.id)
    items_q = db.query(CareContentItem).filter(CareContentItem.program_id == p.id,
                                               CareContentItem.clinic_id == clinic.id,
                                               CareContentItem.audience != "staff")
    fq = db.query(RedFlagRule).filter(RedFlagRule.program_id == p.id)
    if not include_drafts:
        vq = vq.filter(InstructionalVideo.status == "approved")
        items_q = items_q.filter(CareContentItem.status.in_(content.visible_statuses(clinic)))
        fq = fq.filter(RedFlagRule.status == "approved")
    in_scope = lambda cid: cid is None or cid in ids  # noqa: E731
    items = [i for i in items_q.order_by(CareContentItem.kind, CareContentItem.title).all()
             if in_scope(i.course_id) and (include_drafts or not i.expires_at or i.expires_at > now)]
    return {
        "program": program_dict(db, p, clinic), "clinic": clinic_dict(clinic, full=True),
        "courses": out_courses,
        "videos": [video_dict(v) for v in vq.order_by(InstructionalVideo.position).all() if in_scope(v.course_id)],
        "content": [content.item_dict(i) for i in items],
        "red_flags": [flag_dict(r) for r in fq.all() if in_scope(r.course_id)],
        "preview": include_drafts,
    }


@router.get("/p/{clinic_slug}/{program_slug}")
def program_view(clinic_slug: str, program_slug: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    clinic, a = _ctx(db, user, clinic_slug, program_slug)
    d = _program_view(db, clinic, a.program, a.can_see_course)
    d["care_role"] = a.role
    d["scopes"] = a.scopes
    if not a.has("videos"):
        d["videos"] = []
    if not a.has("education"):
        d["content"] = []
    return d


@router.get("/p/{clinic_slug}/{program_slug}/consultation")
def get_consultation(clinic_slug: str, program_slug: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    clinic, a = _ctx(db, user, clinic_slug, program_slug)
    a.require("chat_history")  # supporters get guides and videos only (server-side, not just a hidden menu)
    c = chat.get_or_create(db, user, a)
    return {"context": chat._context(clinic, a.program, c), "messages": [chat.msg_dict(m) for m in c.messages],
            "device": chat.device_dict(chat.verified_device(db, user, a))}


class SendBody(BaseModel):
    content: str = Field(..., max_length=4000)
    mode: str = "text"


@router.post("/p/{clinic_slug}/{program_slug}/messages")
async def send_message(clinic_slug: str, program_slug: str, body: SendBody, request: Request,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    clinic, a = _ctx(db, user, clinic_slug, program_slug)
    a.require("chat_history")
    return await chat.send(db, user, clinic, a, body.content, body.mode if body.mode in ("text", "voice", "avatar") else "text",
                           request_id=getattr(request.state, "request_id", None))


@router.delete("/p/{clinic_slug}/{program_slug}/messages", status_code=204)
def clear_messages(clinic_slug: str, program_slug: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    clinic, a = _ctx(db, user, clinic_slug, program_slug)
    c = chat.get_or_create(db, user, a)
    db.query(ConsultationMessage).filter_by(consultation_id=c.id).delete()
    c.summary = None
    db.commit()
    return Response(status_code=204)


class HandoffBody(BaseModel):
    reason: str = "patient_request"
    summary: str = Field(..., max_length=2000)


@router.post("/p/{clinic_slug}/{program_slug}/handoffs")
def handoff(clinic_slug: str, program_slug: str, body: HandoffBody, request: Request, response: Response,
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Legacy alias of POST .../requests (review queue). Honors Idempotency-Key."""
    clinic, a = _ctx(db, user, clinic_slug, program_slug)
    c = chat.get_or_create(db, user, a)
    view, created = review.create(db, user, clinic, a, c.id, body.reason, body.summary,
                                  request.headers.get("idempotency-key"))
    response.status_code = 201 if created else 200
    return view


def _sign(video_id: str, exp: int, purpose: str = "p") -> str:
    # purpose "p" = patient link (approved videos only), "s" = studio review link (any status, staff-issued)
    return hmac.new(settings.secret_key.encode(), f"care-video:{purpose}:{video_id}:{exp}".encode(),
                    hashlib.sha256).hexdigest()


PLACEHOLDER_LABEL = ("Approved footage not yet provided by the clinic — placeholder. "
                     "The transcript below is clinic-reviewed.")


def _playback(v: InstructionalVideo, request: Request, purpose: str = "p"):
    """Media playback contract. No approved footage → an explicit placeholder;
    footage is never generated or substituted."""
    base_info = {"video_id": str(v.id), "title": v.title, "reviewer": v.reviewer, "version": v.version,
                 "approved_at": _iso(v.approved_at), "transcript": v.transcript}
    if not v.storage_uri and not v.external_url:
        return {**base_info, "status": "placeholder", "url": None, "captions_url": None, "expires_at": None,
                "placeholder_label": PLACEHOLDER_LABEL}
    if not v.storage_uri:
        return {**base_info, "status": "ready", "url": v.external_url, "expires_at": None}
    exp = int(time.time()) + PLAYBACK_TTL_S
    base = str(request.base_url).rstrip("/")
    q = f"exp={exp}&sig={_sign(str(v.id), exp, purpose)}" + ("&purpose=s" if purpose == "s" else "")
    return {**base_info, "status": "ready", "url": f"{base}/api/care/videos/{v.id}/stream?{q}",
            "captions_url": f"{base}/api/care/videos/{v.id}/captions?{q}" if v.captions_vtt else None,
            "expires_at": _iso(datetime.utcfromtimestamp(exp))}


@router.get("/p/{clinic_slug}/{program_slug}/videos/{video_id}/playback")
def video_playback(clinic_slug: str, program_slug: str, video_id: uuid.UUID, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    clinic, a = _ctx(db, user, clinic_slug, program_slug)
    a.require("videos")
    v = db.query(InstructionalVideo).filter_by(id=video_id, program_id=a.program.id, status="approved").first()
    if not v:
        raise acl.not_found("Video not found")
    if v.course_id:
        course = db.query(CareCourse).filter_by(id=v.course_id).first()
        if not course or not a.can_see_course(course):
            raise acl.not_found("Video not found")
    out = {**_playback(v, request), "is_demo": bool(a.program.is_demo)}
    # Patients get the transcript bound to the approved, hash-pinned transcript version only.
    from app.services.care import integrity

    t = (db.query(CareContentItem).filter_by(video_id=v.id, status="approved")
         .order_by(CareContentItem.version.desc()).first())
    ok = t is not None and integrity.verify(t)
    out["transcript"] = t.body if ok else None
    out["transcript_sha256"] = t.approved_sha256 if ok else None
    out["transcript_version"] = t.version if ok else None
    return out


def _signed_video(db, video_id, exp, sig, purpose: str = "p") -> InstructionalVideo:
    if purpose not in ("p", "s") or exp < time.time() or not hmac.compare_digest(sig, _sign(str(video_id), exp, purpose)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Playback link expired or invalid")
    v = db.query(InstructionalVideo).filter(InstructionalVideo.id == video_id,
                                            InstructionalVideo.program_id.isnot(None)).first()
    if not v:
        raise acl.not_found("Video not found")
    # A signed link must stop working as soon as the video is retired or sent back to draft.
    if purpose == "p" and v.status != "approved":
        raise acl.not_found("Video not found")
    return v


@router.get("/videos/{video_id}/stream")
def stream(video_id: uuid.UUID, exp: int, sig: str, request: Request, purpose: str = "p",
           db: Session = Depends(get_db)):
    v = _signed_video(db, video_id, exp, sig, purpose)
    if not v.storage_uri:
        raise acl.not_found("Video not found")
    from app.services.private_storage import get_private_storage

    data = get_private_storage().read(v.storage_uri)
    size, ctype = len(data), v.content_type or "video/mp4"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, no-store"}
    rng = request.headers.get("range")
    if rng and rng.startswith("bytes="):
        a, _, b = rng[6:].partition("-")
        start, end = int(a or 0), min(int(b) if b else size - 1, size - 1)
        if start >= size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return Response(data[start:end + 1], status_code=206, media_type=ctype, headers=headers)
    return Response(data, media_type=ctype, headers=headers)


@router.get("/videos/{video_id}/captions")
def captions(video_id: uuid.UUID, exp: int, sig: str, purpose: str = "p", db: Session = Depends(get_db)):
    v = _signed_video(db, video_id, exp, sig, purpose)
    if not v.captions_vtt:
        raise acl.not_found("No captions")
    return Response(v.captions_vtt, media_type="text/vtt", headers={"Cache-Control": "private, no-store"})


# ─────────────────────────── studio (clinic staff) ───────────────────────────
def _can_create_clinic(user: User) -> bool:
    return acl.is_admin(user) or str(getattr(user.role, "value", user.role)) == "publisher"


@router.get("/studio/me")
def studio_me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(ClinicStaff, Clinic).join(Clinic, Clinic.id == ClinicStaff.clinic_id)
            .filter(ClinicStaff.user_id == user.id).order_by(Clinic.name).all())
    return {"is_admin": acl.is_admin(user), "can_create_clinic": _can_create_clinic(user),
            "clinics": [{**clinic_dict(c, full=True), "permissions": {k: getattr(s, k) for k in acl.PERMS}}
                        for s, c in rows]}


class ClinicBody(BaseModel):
    slug: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    branding: Optional[Dict[str, Any]] = None
    contact_routes: Optional[List[Dict[str, Any]]] = None
    response_expectation: Optional[str] = None
    is_demo: Optional[bool] = None


def _clean_routes(routes):
    out = []
    for r in routes or []:
        key = str(r.get("key") or "").strip().lower()
        if not key:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Each contact route needs a key")
        out.append({"key": key, "label": str(r.get("label") or key)[:120], "detail": str(r.get("detail") or "")[:300],
                    "hours": str(r.get("hours") or "")[:200]})
    return out


@router.post("/studio/clinics")
def create_clinic(body: ClinicBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not _can_create_clinic(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only publishers or admins can create clinics")
    slug = _slug(body.slug or "")
    if not (body.name or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required")
    if db.query(Clinic).filter_by(slug=slug).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "That clinic slug is taken")
    now = datetime.utcnow()
    c = Clinic(id=uuid.uuid4(), slug=slug, name=body.name.strip()[:255], description=body.description,
               branding=body.branding or {}, contact_routes=_clean_routes(body.contact_routes),
               response_expectation=body.response_expectation, is_demo=bool(body.is_demo), status="active",
               created_by=user.id, created_at=now, updated_at=now)
    db.add(c)
    db.flush()
    # creator manages and publishes; clinical approval and clinical visibility are granted explicitly
    db.add(ClinicStaff(id=uuid.uuid4(), clinic_id=c.id, user_id=user.id, can_manage=True, can_publish=True,
                       can_approve=False, can_view_clinical=False, created_at=now))
    record_audit_event(db, action="care.clinic_created", entity_type="clinic", entity_id=c.id, actor_user_id=user.id,
                       data={"slug": slug})
    db.commit()
    return clinic_dict(c, full=True)


@router.patch("/studio/clinics/{clinic_id}")
def update_clinic(clinic_id: uuid.UUID, body: ClinicBody, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    acl.require_staff(db, user, clinic_id, "can_manage")
    c = db.query(Clinic).filter_by(id=clinic_id).first()
    for k in ("name", "description", "branding", "response_expectation", "is_demo"):
        v = getattr(body, k)
        if v is not None:
            setattr(c, k, v)
    if body.contact_routes is not None:
        c.contact_routes = _clean_routes(body.contact_routes)
    c.updated_at = datetime.utcnow()
    record_audit_event(db, action="care.clinic_updated", entity_type="clinic", entity_id=c.id, actor_user_id=user.id,
                       data={"fields": sorted(k for k, v in body.model_dump().items() if v is not None)})
    db.commit()
    return clinic_dict(c, full=True)


class StaffBody(BaseModel):
    user: Optional[str] = None  # username or email
    can_manage: bool = False
    can_publish: bool = False
    can_approve: bool = False
    can_view_clinical: bool = False
    display_name: Optional[str] = None


def _find_user(db, ident: str) -> User:
    ident = (ident or "").strip()
    u = db.query(User).filter((User.username == ident) | (User.email == ident.lower())).first()
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No user with that username or email")
    return u


@router.get("/studio/clinics/{clinic_id}/staff")
def list_staff(clinic_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    acl.require_staff(db, user, clinic_id, "can_manage")
    rows = db.query(ClinicStaff, User).join(User, User.id == ClinicStaff.user_id).filter(ClinicStaff.clinic_id == clinic_id).all()
    return {"staff": [{"id": str(s.id), "username": u.username, "display_name": s.display_name,
                       **{k: getattr(s, k) for k in acl.PERMS}} for s, u in rows]}


@router.post("/studio/clinics/{clinic_id}/staff")
def upsert_staff(clinic_id: uuid.UUID, body: StaffBody, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    acl.require_staff(db, user, clinic_id, "can_manage")
    target = _find_user(db, body.user or "")
    row = db.query(ClinicStaff).filter_by(clinic_id=clinic_id, user_id=target.id).first()
    if not row:
        row = ClinicStaff(id=uuid.uuid4(), clinic_id=clinic_id, user_id=target.id, created_at=datetime.utcnow())
        db.add(row)
    for k in acl.PERMS:
        setattr(row, k, getattr(body, k))
    row.display_name = body.display_name
    record_audit_event(db, action="care.staff_set", entity_type="clinic", entity_id=clinic_id, actor_user_id=user.id,
                       data={"target": str(target.id), **{k: getattr(body, k) for k in acl.PERMS}})
    db.commit()
    return {"ok": True}


# templates: everyone in studio reads; platform admin writes
class TemplateBody(BaseModel):
    slug: Optional[str] = None
    name: Optional[str] = None
    care_area: Optional[str] = None
    description: Optional[str] = None
    default_config: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


@router.get("/studio/templates")
def list_templates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(ProgramTemplate)
    if not acl.is_admin(user):
        q = q.filter_by(status="active")
    return {"templates": [template_dict(t) for t in q.order_by(ProgramTemplate.name).all()]}


@router.post("/admin/templates")
def create_template(body: TemplateBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    acl.require_admin(user)
    slug = _slug(body.slug or "")
    if db.query(ProgramTemplate).filter_by(slug=slug).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Template slug is taken")
    if not (body.name or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required")
    t = ProgramTemplate(id=uuid.uuid4(), slug=slug, name=body.name.strip(), care_area=body.care_area,
                        description=body.description, default_config=body.default_config or {}, status="active",
                        created_by=user.id, created_at=datetime.utcnow())
    db.add(t)
    record_audit_event(db, action="care.template_created", entity_type="program_template", entity_id=t.id,
                       actor_user_id=user.id, data={"slug": slug})
    db.commit()
    return template_dict(t)


@router.patch("/admin/templates/{template_id}")
def update_template(template_id: uuid.UUID, body: TemplateBody, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    acl.require_admin(user)
    t = db.query(ProgramTemplate).filter_by(id=template_id).first()
    if not t:
        raise acl.not_found()
    for k in ("name", "care_area", "description", "default_config"):
        if getattr(body, k) is not None:
            setattr(t, k, getattr(body, k))
    if body.status in ("active", "archived"):
        t.status = body.status
    db.commit()
    return template_dict(t)


# personas
class PersonaBody(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    specialty: Optional[str] = None
    prompt: Optional[str] = Field(None, max_length=4000)
    avatar_id: Optional[str] = None
    liveavatar_avatar_id: Optional[str] = None
    variant: Optional[str] = None
    voice_id: Optional[str] = None
    gender: Optional[str] = None
    is_demo: Optional[bool] = None
    status: Optional[str] = None


def _apply_persona(db, p: DoctorPersona, body: PersonaBody, user: User):
    for k in ("name", "title", "specialty", "prompt", "liveavatar_avatar_id", "variant", "voice_id", "is_demo"):
        v = getattr(body, k)
        if v is not None:
            setattr(p, k, v.strip() if isinstance(v, str) else v)
    if body.gender is not None:
        if body.gender not in ("female", "male", ""):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "gender must be female or male")
        p.gender = body.gender or None
    if body.status in ("active", "archived"):
        p.status = body.status
    if body.avatar_id is not None:
        aid = _uuid(body.avatar_id)
        if aid:
            av = db.query(Avatar).filter_by(id=aid).first()
            if not av or (av.publisher_id != user.id and not av.is_published):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Avatar not found")
        p.avatar_id = aid


@router.get("/studio/clinics/{clinic_id}/personas")
def list_personas(clinic_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    acl.require_staff(db, user, clinic_id, "can_publish")
    return {"personas": [persona_dict(p, True) for p in db.query(DoctorPersona).filter_by(clinic_id=clinic_id)
                         .order_by(DoctorPersona.name).all()]}


@router.post("/studio/clinics/{clinic_id}/personas")
def create_persona(clinic_id: uuid.UUID, body: PersonaBody, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    acl.require_staff(db, user, clinic_id, "can_publish")
    if not (body.name or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required")
    now = datetime.utcnow()
    p = DoctorPersona(id=uuid.uuid4(), clinic_id=clinic_id, name="", status="active", created_at=now, updated_at=now)
    _apply_persona(db, p, body, user)
    db.add(p)
    record_audit_event(db, action="care.persona_created", entity_type="doctor_persona", entity_id=p.id,
                       actor_user_id=user.id, data={"clinic_id": str(clinic_id)})
    db.commit()
    return persona_dict(p, True)


@router.patch("/studio/personas/{persona_id}")
def update_persona(persona_id: uuid.UUID, body: PersonaBody, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    p = db.query(DoctorPersona).filter_by(id=persona_id).first()
    if not p:
        raise acl.not_found()
    acl.require_staff(db, user, p.clinic_id, "can_publish")
    _apply_persona(db, p, body, user)
    p.updated_at = datetime.utcnow()
    db.commit()
    return persona_dict(p, True)


@router.get("/studio/avatar-options")
def avatar_options(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Choices for persona setup: the user's / published 3D avatars, configured
    LiveAvatar ids and ElevenLabs voices (names and ids only, never keys)."""
    import os

    import httpx

    avatars = (db.query(Avatar).filter((Avatar.publisher_id == user.id) | (Avatar.is_published.is_(True)))
               .order_by(Avatar.name).limit(200).all())
    live = [{"id": os.getenv(k), "label": label} for k, label in
            (("LIVEAVATAR_DEFAULT_AVATAR_ID", "Default LiveAvatar"),) if os.getenv(k)]
    voices, voice_error = [], None
    key = os.getenv("ELEVENLABS_API_KEY") or getattr(settings, "elevenlabs_api_key", "")
    if key:
        try:
            r = httpx.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key}, timeout=8)
            if r.status_code == 200:
                voices = [{"id": v["voice_id"], "name": v.get("name"), "category": v.get("category")}
                          for v in r.json().get("voices", [])]
            else:
                voice_error = f"ElevenLabs returned {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            voice_error = type(exc).__name__
    else:
        voice_error = "ELEVENLABS_API_KEY is not configured"
    return {"avatars": [{"id": str(a.id), "name": a.name} for a in avatars], "liveavatar": live,
            "voices": voices, "voice_error": voice_error}


# programs
class ProgramBody(BaseModel):
    template_id: Optional[str] = None
    slug: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    persona_id: Optional[str] = None
    enrollment_policy: Optional[str] = None
    branding: Optional[Dict[str, Any]] = None
    position: Optional[int] = None


def _program_for_staff(db, user, program_id, perm="can_publish") -> CareProgram:
    p = db.query(CareProgram).filter_by(id=program_id).first()
    if not p or not p.clinic_ref_id:
        raise acl.not_found("Program not found")
    acl.require_staff(db, user, p.clinic_ref_id, perm)
    return p


def _apply_program(db, p: CareProgram, body: ProgramBody):
    for k in ("name", "description", "branding", "position"):
        v = getattr(body, k)
        if v is not None:
            setattr(p, k, v)
    if body.enrollment_policy is not None:
        if body.enrollment_policy not in ("open", "staff"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "enrollment_policy must be open or staff")
        p.enrollment_policy = body.enrollment_policy
    if body.template_id is not None:
        tid = _uuid(body.template_id)
        if tid and not db.query(ProgramTemplate).filter_by(id=tid, status="active").first():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
        p.template_id = tid
    if body.persona_id is not None:
        pid = _uuid(body.persona_id)
        if pid and not db.query(DoctorPersona).filter_by(id=pid, clinic_id=p.clinic_ref_id).first():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona not found in this clinic")
        p.persona_id = pid


@router.get("/studio/clinics/{clinic_id}/programs")
def list_programs(clinic_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    acl.require_staff(db, user, clinic_id, "can_publish")
    clinic = db.query(Clinic).filter_by(id=clinic_id).first()
    ps = db.query(CareProgram).filter_by(clinic_ref_id=clinic_id).order_by(CareProgram.position, CareProgram.name).all()
    return {"programs": [program_dict(db, p, clinic) for p in ps]}


@router.post("/studio/clinics/{clinic_id}/programs")
def create_program(clinic_id: uuid.UUID, body: ProgramBody, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    acl.require_staff(db, user, clinic_id, "can_publish")
    slug = _slug(body.slug or "")
    if db.query(CareProgram).filter_by(slug=slug).first():
        # CareProgram.slug is globally unique (legacy constraint)
        raise HTTPException(status.HTTP_409_CONFLICT, "That program slug is taken; try adding the clinic name")
    if not (body.name or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required")
    now = datetime.utcnow()
    clinic = db.query(Clinic).filter_by(id=clinic_id).first()
    p = CareProgram(id=uuid.uuid4(), slug=slug, name="", clinic_ref_id=clinic_id, clinic_id=clinic.slug,
                    status="draft", enrollment_policy="staff", is_public=False, is_demo=clinic.is_demo,
                    created_at=now, updated_at=now)
    _apply_program(db, p, body)
    db.add(p)
    record_audit_event(db, action="care.program_created", entity_type="care_program", entity_id=p.id,
                       actor_user_id=user.id, data={"slug": slug, "clinic_id": str(clinic_id)})
    db.commit()
    return program_dict(db, p, clinic)


@router.patch("/studio/programs/{program_id}")
def update_program(program_id: uuid.UUID, body: ProgramBody, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    p = _program_for_staff(db, user, program_id)
    _apply_program(db, p, body)
    p.updated_at = datetime.utcnow()
    db.commit()
    return program_dict(db, p, db.query(Clinic).filter_by(id=p.clinic_ref_id).first())


@router.post("/studio/programs/{program_id}/publish")
def publish_program(program_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _set_program_status(db, user, program_id, "publish")


@router.post("/studio/programs/{program_id}/unpublish")
def unpublish_program(program_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _set_program_status(db, user, program_id, "unpublish")


def _set_program_status(db, user, program_id, action):
    p = _program_for_staff(db, user, program_id)
    p.status = "published" if action == "publish" else "unpublished"
    p.updated_at = datetime.utcnow()
    record_audit_event(db, action=f"care.program_{action}", entity_type="care_program", entity_id=p.id,
                       actor_user_id=user.id, data={})
    db.commit()
    return {"status": p.status}


@router.get("/studio/programs/{program_id}")
def studio_program(program_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Full workspace view (incl. drafts); also the publisher preview."""
    p = _program_for_staff(db, user, program_id)
    clinic = db.query(Clinic).filter_by(id=p.clinic_ref_id).first()
    d = _program_view(db, clinic, p, lambda c: True, include_drafts=True)
    d["content"] = [content.item_dict(i) for i in db.query(CareContentItem).filter_by(program_id=p.id)
                    .order_by(CareContentItem.lineage_id, CareContentItem.version.desc()).all()]
    return d


# courses + lessons
class CourseBody(BaseModel):
    slug: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    position: Optional[int] = None
    status: Optional[str] = None
    requires_entitlement: Optional[bool] = None


def _apply_course(c: CareCourse, body: CourseBody):
    for k in ("title", "description", "position", "requires_entitlement"):
        if getattr(body, k) is not None:
            setattr(c, k, getattr(body, k))
    if body.status is not None:
        if body.status not in ("draft", "published", "unpublished"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid status")
        c.status = body.status
    c.updated_at = datetime.utcnow()


@router.post("/studio/programs/{program_id}/courses")
def create_course(program_id: uuid.UUID, body: CourseBody, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    p = _program_for_staff(db, user, program_id)
    slug = _slug(body.slug or "")
    if db.query(CareCourse).filter_by(program_id=p.id, slug=slug).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Course slug is taken in this program")
    if not (body.title or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Title is required")
    n = db.query(CareCourse).filter_by(program_id=p.id).count()
    c = CareCourse(id=uuid.uuid4(), program_id=p.id, slug=slug, title="", position=n, status="draft",
                   created_at=datetime.utcnow())
    _apply_course(c, body)
    db.add(c)
    db.commit()
    return course_dict(c, [])


def _course_for_staff(db, user, course_id) -> CareCourse:
    c = db.query(CareCourse).filter_by(id=course_id).first()
    if not c:
        raise acl.not_found()
    _program_for_staff(db, user, c.program_id)
    return c


@router.patch("/studio/courses/{course_id}")
def update_course(course_id: uuid.UUID, body: CourseBody, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    c = _course_for_staff(db, user, course_id)
    _apply_course(c, body)
    db.commit()
    return course_dict(c)


@router.delete("/studio/courses/{course_id}", status_code=204)
def delete_course(course_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = _course_for_staff(db, user, course_id)
    if c.status == "published":
        raise HTTPException(status.HTTP_409_CONFLICT, "Unpublish the course before deleting it")
    db.delete(c)
    db.commit()
    return Response(status_code=204)


class LessonBody(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    position: Optional[int] = None
    status: Optional[str] = None


@router.post("/studio/courses/{course_id}/lessons")
def create_lesson(course_id: uuid.UUID, body: LessonBody, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    c = _course_for_staff(db, user, course_id)
    if not (body.title or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Title is required")
    n = db.query(CareLesson).filter_by(course_id=c.id).count()
    l = CareLesson(id=uuid.uuid4(), course_id=c.id, title=body.title.strip(), body=body.body,
                   position=body.position if body.position is not None else n,
                   status=body.status if body.status in ("draft", "published") else "draft",
                   created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    db.add(l)
    db.commit()
    return {"id": str(l.id), "title": l.title, "status": l.status, "position": l.position}


@router.patch("/studio/lessons/{lesson_id}")
def update_lesson(lesson_id: uuid.UUID, body: LessonBody, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    l = db.query(CareLesson).filter_by(id=lesson_id).first()
    if not l:
        raise acl.not_found()
    _course_for_staff(db, user, l.course_id)
    for k in ("title", "body", "position"):
        if getattr(body, k) is not None:
            setattr(l, k, getattr(body, k))
    if body.status in ("draft", "published", "unpublished"):
        l.status = body.status
    l.updated_at = datetime.utcnow()
    db.commit()
    return {"id": str(l.id), "title": l.title, "status": l.status, "position": l.position}


# content items
class ContentBody(BaseModel):
    course_id: Optional[str] = None
    kind: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    language: Optional[str] = None
    audience: Optional[str] = None
    applicability: Optional[str] = None
    source: Optional[str] = None
    expires_at: Optional[str] = None
    is_demo: Optional[bool] = None


def _content_changes(db, p: CareProgram, body: ContentBody) -> Dict[str, Any]:
    ch: Dict[str, Any] = {}
    for k in ("title", "body", "language", "applicability", "source", "is_demo"):
        if getattr(body, k) is not None:
            ch[k] = getattr(body, k)
    if body.kind is not None:
        if body.kind not in content.KINDS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"kind must be one of {content.KINDS}")
        ch["kind"] = body.kind
    if body.audience is not None:
        if body.audience not in content.AUDIENCES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid audience")
        ch["audience"] = body.audience
    if body.course_id is not None:
        cid = _uuid(body.course_id)
        if cid and not db.query(CareCourse).filter_by(id=cid, program_id=p.id).first():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not in this program")
        ch["course_id"] = cid
    if body.expires_at is not None:
        ch["expires_at"] = _date(body.expires_at)
    return ch


@router.post("/studio/programs/{program_id}/content")
def create_content(program_id: uuid.UUID, body: ContentBody, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    p = _program_for_staff(db, user, program_id)
    ch = _content_changes(db, p, body)
    if not ch.get("title") or not ch.get("body") or not ch.get("kind"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "kind, title and body are required")
    now = datetime.utcnow()
    lid = uuid.uuid4()
    item = CareContentItem(id=uuid.uuid4(), lineage_id=lid, version=1, clinic_id=p.clinic_ref_id, program_id=p.id,
                           status="draft", created_by=user.id, created_at=now, updated_at=now,
                           **{"language": "en", "audience": "patient", **ch})
    db.add(item)
    record_audit_event(db, action="care_content.create", entity_type="care_content_item", entity_id=item.id,
                       actor_user_id=user.id, data={"kind": item.kind})
    db.commit()
    return content.item_dict(item)


def _item_for_staff(db, user, item_id, perm="can_publish") -> CareContentItem:
    it = db.query(CareContentItem).filter_by(id=item_id).first()
    if not it:
        raise acl.not_found()
    acl.require_staff(db, user, it.clinic_id, perm)
    return it


@router.patch("/studio/content/{item_id}")
def edit_content(item_id: uuid.UUID, body: ContentBody, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    it = _item_for_staff(db, user, item_id)
    if it.kind in content.SYSTEM_KINDS:
        raise HTTPException(status.HTTP_409_CONFLICT, "Video transcripts are edited on the video and re-reviewed with it")
    p = db.query(CareProgram).filter_by(id=it.program_id).first()
    target = content.new_version(db, it, user, **_content_changes(db, p, body))
    db.commit()
    return content.item_dict(target)


class TransitionBody(BaseModel):
    reviewer: Optional[str] = None


@router.post("/studio/content/{item_id}/{action}")
def content_action(item_id: uuid.UUID, action: str, body: TransitionBody = TransitionBody(),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    perm = "can_approve" if action == "approve" else "can_publish"
    it = _item_for_staff(db, user, item_id, perm)
    if it.kind in content.SYSTEM_KINDS:
        raise HTTPException(status.HTTP_409_CONFLICT, "Video transcripts follow the video's review; act on the video")
    content.transition(db, it, action, user, body.reviewer)
    db.commit()
    return content.item_dict(it)


# red flags
class FlagBody(BaseModel):
    course_id: Optional[str] = None
    symptom: Optional[str] = None
    match_terms: Optional[List[str]] = None
    clinic_action: Optional[str] = None
    urgency: Optional[str] = None
    contact_route: Optional[str] = None
    applicability: Optional[str] = None
    reviewer: Optional[str] = None
    review_date: Optional[str] = None
    is_demo: Optional[bool] = None


def _apply_flag(db, r: RedFlagRule, p: CareProgram, body: FlagBody):
    for k in ("symptom", "clinic_action", "contact_route", "applicability", "reviewer", "is_demo"):
        if getattr(body, k) is not None:
            setattr(r, k, getattr(body, k))
    if body.match_terms is not None:
        r.match_terms = [t.strip().lower() for t in body.match_terms if t and t.strip()][:40]
    if body.urgency is not None:
        if body.urgency not in URGENCIES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"urgency must be one of {URGENCIES}")
        r.urgency = body.urgency
    if body.review_date is not None:
        r.review_date = _date(body.review_date)
    if body.course_id is not None:
        cid = _uuid(body.course_id)
        if cid and not db.query(CareCourse).filter_by(id=cid, program_id=p.id).first():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not in this program")
        r.course_id = cid
    r.updated_at = datetime.utcnow()


@router.post("/studio/programs/{program_id}/red-flags")
def create_flag(program_id: uuid.UUID, body: FlagBody, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    p = _program_for_staff(db, user, program_id)
    if not (body.symptom and body.clinic_action and body.urgency):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "symptom, clinic_action and urgency are required")
    r = RedFlagRule(id=uuid.uuid4(), clinic_id=p.clinic_ref_id, program_id=p.id, symptom="", clinic_action="",
                    urgency="routine", status="draft", match_terms=[], created_at=datetime.utcnow())
    _apply_flag(db, r, p, body)
    db.add(r)
    db.commit()
    return flag_dict(r)


@router.patch("/studio/red-flags/{flag_id}")
def edit_flag(flag_id: uuid.UUID, body: FlagBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = db.query(RedFlagRule).filter_by(id=flag_id).first()
    if not r:
        raise acl.not_found()
    p = _program_for_staff(db, user, r.program_id)
    _apply_flag(db, r, p, body)
    r.status = "draft"  # any edit needs re-approval
    db.commit()
    return flag_dict(r)


@router.post("/studio/red-flags/{flag_id}/{action}")
def flag_action(flag_id: uuid.UUID, action: str, body: TransitionBody = TransitionBody(),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = db.query(RedFlagRule).filter_by(id=flag_id).first()
    if not r:
        raise acl.not_found()
    if action == "approve":
        acl.require_staff(db, user, r.clinic_id, "can_approve")
        if not (body.reviewer or r.reviewer):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Approval needs the reviewing clinician's name")
        if not r.match_terms:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Add at least one phrase that triggers this warning")
        r.reviewer = body.reviewer or r.reviewer
        r.review_date = r.review_date or datetime.utcnow()
        r.status = "approved"
    elif action == "retire":
        acl.require_staff(db, user, r.clinic_id, "can_publish")
        r.status = "retired"
    else:
        raise acl.not_found()
    record_audit_event(db, action=f"care.red_flag_{action}", entity_type="red_flag_rule", entity_id=r.id,
                       actor_user_id=user.id, data={"urgency": r.urgency})
    db.commit()
    return flag_dict(r)


# videos
@router.post("/studio/programs/{program_id}/videos")
async def upload_video(program_id: uuid.UUID, title: str = Form(...), description: str = Form(""),
                       language: str = Form("en"), course_id: str = Form(""), lesson_id: str = Form(""),
                       external_url: str = Form(""), transcript: str = Form(""),
                       file: Optional[UploadFile] = File(None), captions_file: Optional[UploadFile] = File(None),
                       thumbnail: Optional[UploadFile] = File(None),
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _program_for_staff(db, user, program_id)
    cid, lid = _uuid(course_id), _uuid(lesson_id)
    if cid and not db.query(CareCourse).filter_by(id=cid, program_id=p.id).first():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not in this program")
    if lid and not db.query(CareLesson).filter_by(id=lid, course_id=cid).first():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not in that course")
    from app.services.private_storage import get_private_storage

    store = get_private_storage()
    n = db.query(InstructionalVideo).filter_by(program_id=p.id).count()
    v = InstructionalVideo(id=uuid.uuid4(), title=title[:255], description=description or None, language=language or "en",
                           audience="both", clinic_id=None, approval_status="draft", status="draft", program_id=p.id,
                           course_id=cid, lesson_id=lid, position=n, external_url=external_url or None,
                           transcript=transcript or None, uploaded_by=user.id)
    owner = str(p.clinic_ref_id)
    if file is not None and file.filename:
        data = await file.read()
        if len(data) > MAX_VIDEO_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Video is larger than 500 MB")
        if not (file.content_type or "").startswith("video/"):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a video file")
        s = store.save(data, kind="care-videos", owner=owner, filename=file.filename, content_type=file.content_type)
        v.storage_uri, v.content_type = s.uri, file.content_type
    if captions_file is not None and captions_file.filename:
        text = (await captions_file.read()).decode("utf-8", errors="replace")
        v.captions_vtt = text if text.lstrip().startswith("WEBVTT") else None
        v.transcript = v.transcript or re.sub(r"(?m)^(WEBVTT.*|\d+|[\d:.]+ --> [\d:.]+.*)$", "", text).strip()
    if thumbnail is not None and thumbnail.filename:
        if not (thumbnail.content_type or "").startswith("image/"):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Thumbnail must be an image")
        s = store.save(await thumbnail.read(), kind="care-thumbnails", owner=owner, filename=thumbnail.filename,
                       content_type=thumbnail.content_type)
        v.thumbnail_uri = s.uri
    if not v.storage_uri and not v.external_url:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Provide a video file or a URL")
    db.add(v)
    record_audit_event(db, action="care.video_uploaded", entity_type="instructional_video", entity_id=v.id,
                       actor_user_id=user.id, data={"program_id": str(p.id)})
    db.commit()
    return video_dict(v)


@router.post("/studio/videos/{video_id}/{action}")
def video_action(video_id: uuid.UUID, action: str, body: TransitionBody = TransitionBody(),
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    v = db.query(InstructionalVideo).filter(InstructionalVideo.id == video_id,
                                            InstructionalVideo.program_id.isnot(None)).first()
    if not v:
        raise acl.not_found()
    p = db.query(CareProgram).filter_by(id=v.program_id).first()
    if action not in content.TRANSITIONS:
        raise acl.not_found()
    acl.require_staff(db, user, p.clinic_ref_id, "can_approve" if action == "approve" else "can_publish")
    frm, to = content.TRANSITIONS[action]
    if (v.status or "draft") != frm:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot {action} a video in status {v.status}")
    if action == "approve":
        if not (body.reviewer or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Approval needs the reviewing clinician's name")
        v.reviewer = body.reviewer.strip()[:255]
        v.approved_at = datetime.utcnow()
    v.status = to
    v.approval_status = to
    content.sync_video_transcript(db, v, user)  # transcript shares the video's review lifecycle
    record_audit_event(db, action=f"care.video_{action}", entity_type="instructional_video", entity_id=v.id,
                       actor_user_id=user.id, data={"status": to})
    db.commit()
    return video_dict(v)


@router.get("/studio/videos/{video_id}/playback")
def studio_video_playback(video_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    v = db.query(InstructionalVideo).filter(InstructionalVideo.id == video_id,
                                            InstructionalVideo.program_id.isnot(None)).first()
    if not v:
        raise acl.not_found()
    _program_for_staff(db, user, v.program_id)
    return _playback(v, request, "s")


# entitlements (staff-granted access)
class GrantBody(BaseModel):
    user: str
    course_id: Optional[str] = None
    care_role: str = "patient"


@router.get("/studio/programs/{program_id}/entitlements")
def list_grants(program_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _program_for_staff(db, user, program_id, "can_manage")
    rows = (db.query(CareEntitlement, User).join(User, User.id == CareEntitlement.user_id)
            .filter(CareEntitlement.program_id == p.id, CareEntitlement.revoked_at.is_(None)).all())
    return {"entitlements": [{"id": str(e.id), "username": u.username, "care_role": e.care_role, "source": e.source,
                              "course_id": str(e.course_id) if e.course_id else None,
                              "created_at": _iso(e.created_at)} for e, u in rows]}


@router.post("/studio/programs/{program_id}/entitlements")
def grant(program_id: uuid.UUID, body: GrantBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _program_for_staff(db, user, program_id, "can_manage")
    target = _find_user(db, body.user)
    cid = _uuid(body.course_id)
    if cid and not db.query(CareCourse).filter_by(id=cid, program_id=p.id).first():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not in this program")
    if body.care_role not in ("patient", "caregiver"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "care_role must be patient or caregiver")
    e = CareEntitlement(id=uuid.uuid4(), user_id=target.id, clinic_id=p.clinic_ref_id, program_id=p.id, course_id=cid,
                        care_role=body.care_role, source="staff_grant", granted_by=user.id, created_at=datetime.utcnow())
    db.add(e)
    record_audit_event(db, action="care.entitlement_granted", entity_type="care_program", entity_id=p.id,
                       actor_user_id=user.id, data={"target": str(target.id), "course_id": str(cid) if cid else None})
    db.commit()
    return {"id": str(e.id)}


@router.delete("/studio/entitlements/{ent_id}", status_code=204)
def revoke(ent_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    e = db.query(CareEntitlement).filter_by(id=ent_id).first()
    if not e:
        raise acl.not_found()
    acl.require_staff(db, user, e.clinic_id, "can_manage")
    e.revoked_at = datetime.utcnow()
    record_audit_event(db, action="care.entitlement_revoked", entity_type="care_entitlement", entity_id=e.id,
                       actor_user_id=user.id, data={})
    db.commit()
    return Response(status_code=204)


@router.get("/studio/clinics/{clinic_id}/handoffs")
def list_handoffs(clinic_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    acl.require_staff(db, user, clinic_id, "can_view_clinical")
    rows = db.query(CareHandoff).filter_by(clinic_id=clinic_id).order_by(CareHandoff.created_at.desc()).limit(200).all()
    return {"handoffs": [{"id": str(h.id), "program_id": str(h.program_id), "reason": h.reason, "summary": h.summary,
                          "status": h.status, "simulated": h.simulated, "created_at": _iso(h.created_at)} for h in rows]}


# ─────────────────────────── admin ───────────────────────────
@router.get("/admin/clinics")
def admin_clinics(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Orchestration view: clinic metadata and counts only — no conversations."""
    acl.require_admin(user)
    out = []
    for c in db.query(Clinic).order_by(Clinic.name).all():
        out.append({**clinic_dict(c, full=True),
                    "programs": db.query(CareProgram).filter_by(clinic_ref_id=c.id).count(),
                    "staff": db.query(ClinicStaff).filter_by(clinic_id=c.id).count()})
    return {"clinics": out}


@router.get("/admin/integrations")
def integrations(live: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    acl.require_admin(user)
    from app.services.care.integrations import status_report

    return status_report(db, live=live)


# ─────────────────────────── MYOS: first-run guide, history, home ───────────────────────────
class OnboardingBody(BaseModel):
    action: str  # complete | reset


def _guide_kind(db: Session, user: User) -> str:
    if user.role in ("publisher", "admin"):
        return "publisher"
    roles = {e.care_role for e in db.query(CareEntitlement).filter_by(user_id=user.id, revoked_at=None).all()}
    return "supporter" if roles and roles <= {"supporter"} else "patient"


@router.get("/me/onboarding")
def get_onboarding(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"completed_at": _iso(user.onboarding_completed_at), "show": user.onboarding_completed_at is None,
            "kind": _guide_kind(db, user)}


@router.post("/me/onboarding")
def set_onboarding(body: OnboardingBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.action not in ("complete", "reset"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown action")
    user.onboarding_completed_at = datetime.utcnow() if body.action == "complete" else None
    db.commit()
    return get_onboarding(db, user)


@router.get("/me/conversations")
def my_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """One entry per program conversation (newest first) with dates, answered-question count, the last
    real exchange and this user's own requests. Three queries in total, no N+1."""
    from sqlalchemy import func

    progs = my_programs(db, user)["programs"]
    by_id = {p["id"]: p for p in progs}
    if not by_id:
        return {"conversations": []}
    convs = (db.query(Consultation).filter(Consultation.user_id == user.id,
                                           Consultation.program_id.in_([uuid.UUID(i) for i in by_id])).all())
    cids = [c.id for c in convs]
    stats = dict((cid, (n, last)) for cid, n, last in (
        db.query(ConsultationMessage.consultation_id, func.count(ConsultationMessage.id), func.max(ConsultationMessage.created_at))
        .filter(ConsultationMessage.consultation_id.in_(cids), ConsultationMessage.sender == "assistant",
                ConsultationMessage.provenance == "ai_generated")
        .group_by(ConsultationMessage.consultation_id).all())) if cids else {}
    reqs: Dict[str, list] = {}
    for h in (db.query(CareHandoff).filter(CareHandoff.user_id == user.id,
                                           CareHandoff.program_id.in_([uuid.UUID(i) for i in by_id]))
              .order_by(CareHandoff.created_at.desc()).limit(200).all()):
        reqs.setdefault(str(h.program_id), []).append(
            {"id": str(h.id), "summary": h.summary, "state": "answered" if h.status in ("replied", "closed") else "waiting",
             "created_at": _iso(h.created_at)})
    out = []
    for c in convs:
        p = by_id[str(c.program_id)]
        last = (db.query(ConsultationMessage).filter_by(consultation_id=c.id)
                .order_by(ConsultationMessage.created_at.desc()).limit(2).all())
        q = next((m for m in last if m.sender == "user"), None)
        a = next((m for m in last if m.sender == "assistant"), None)
        n, last_at = stats.get(c.id, (0, None))
        out.append({"program": {"slug": p["slug"], "name": p["name"], "clinic": p["clinic"]["slug"]},
                    "twin": p["persona"], "started_at": _iso(c.created_at),
                    "last_activity_at": _iso(c.last_activity_at or last_at or c.created_at),
                    "answered_questions": n,
                    "last_exchange": {"question": q.content[:300], "answer": a.content[:300]} if q and a else None,
                    "requests": reqs.get(str(c.program_id), [])})
    for pid, p in by_id.items():
        if not any(o["program"]["slug"] == p["slug"] for o in out) and reqs.get(pid):
            out.append({"program": {"slug": p["slug"], "name": p["name"], "clinic": p["clinic"]["slug"]},
                        "twin": p["persona"], "started_at": None, "last_activity_at": reqs[pid][0]["created_at"],
                        "answered_questions": 0, "last_exchange": None, "requests": reqs[pid]})
    out.sort(key=lambda o: o["last_activity_at"] or "", reverse=True)
    return {"conversations": out}


@router.get("/health/model")
async def model_health(request: Request):
    from app.services.care import health

    r = await health.check_llm(live=False, request_id=getattr(request.state, "request_id", None))
    return {"service": "model", "ok": r.get("ok"), "error_kind": r.get("error_kind")}
