"""MYO'S Fertility API: IVF Care program, roles, persistent consultation,
knowledge ingestion, instructional videos and patient context."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database.connection import get_db
from app.database.models import (
    CareProgramMembership,
    FertilityKnowledgeChunk,
    FertilityKnowledgeDocument,
    InstructionalVideo,
    PatientContextEntry,
    User,
)
from app.dependencies.auth import get_current_user
from app.services.fertility import consultation as svc
from app.services.fertility import doctor, knowledge

router = APIRouter(prefix="/api/fertility", tags=["fertility"])

CLINIC_ADMIN_ROLES = {"admin", "publisher"}  # publisher == clinic administrator in MYO'S Fertility
MAX_VIDEO_BYTES = 500 * 1024 * 1024
PLAYBACK_TTL_S = 15 * 60


def _clinic_admin(user: User) -> User:
    if (user.role or "") not in CLINIC_ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Clinic administrator access required")
    return user


class JoinBody(BaseModel):
    care_role: str = Field(..., description="patient | partner")
    treatment_stage: Optional[str] = None


class MessageBody(BaseModel):
    content: str
    mode: str = "text"


class ModeBody(BaseModel):
    mode: str


class EscalationBody(BaseModel):
    category: str = "unspecified"
    summary: str = ""


class ContextBody(BaseModel):
    kind: str = "note"
    content: str


class KnowledgeDocBody(BaseModel):
    title: str
    text: str
    source_type: str = "general_education"
    approval_status: str = "demo_unreviewed"
    audience: str = "both"
    topic: Optional[str] = None
    clinic_id: Optional[str] = None
    version: str = "1"


def _membership_dict(m: Optional[CareProgramMembership]):
    if m is None:
        return None
    return {"care_role": m.care_role, "treatment_stage": m.treatment_stage,
            "authorized_scopes": m.authorized_scopes or [], "joined_at": m.joined_at.isoformat() + "Z" if m.joined_at else None}


@router.get("/program")
def get_program(db: Session = Depends(get_db)):
    """Public: IVF Care and the General Fertility Doctor. No enrollment needed to view."""
    p = svc.get_program(db)
    return {
        "slug": p.slug, "name": p.name, "description": p.description, "is_public": p.is_public,
        "doctor": doctor.DOCTOR, "treatment_stages": doctor.TREATMENT_STAGES,
        "suggested_questions": doctor.SUGGESTED_QUESTIONS, "knowledge_phase": knowledge.knowledge_phase(),
    }


@router.get("/me")
def get_me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = svc.get_program(db)
    m = svc.get_membership(db, user.id, p)
    return {"membership": _membership_dict(m),
            "suggested_questions": doctor.suggested_questions(m.care_role if m else "patient", m.treatment_stage if m else None)}


@router.post("/program/join")
def join_program(body: JoinBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Join IVF Care directly (no publisher approval) and set the role."""
    m = svc.join(db, user.id, body.care_role, body.treatment_stage)
    c = svc.get_or_create_consultation(db, user.id)
    return {"membership": _membership_dict(m), "consultation_id": str(c.id)}


@router.get("/suggested-questions")
def suggested(role: str = "patient", stage: Optional[str] = None):
    return {"role": role, "stage": stage, "questions": doctor.suggested_questions(role, stage)}


@router.get("/consultation")
def get_consultation(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Reopen (or create once) the user's single IVF Care consultation."""
    c = svc.get_or_create_consultation(db, user.id)
    return svc.consultation_dict(c)


@router.get("/consultation/summary")
def consultation_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = svc.get_program(db)
    if svc.get_membership(db, user.id, p) is None:
        return {"consultation": None}
    c = svc.get_or_create_consultation(db, user.id)
    return {"consultation": svc.consultation_dict(c, include_messages=False)}


@router.post("/consultation/{consultation_id}/messages")
async def post_message(consultation_id: uuid.UUID, body: MessageBody, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    return await svc.send(db, user.id, consultation_id, body.content, body.mode)


@router.post("/consultation/{consultation_id}/mode")
def set_mode(consultation_id: uuid.UUID, body: ModeBody, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    c = svc.own_consultation(db, user.id, consultation_id)
    if body.mode not in doctor.MODES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown mode")
    c.last_mode = body.mode
    db.commit()
    return {"id": str(c.id), "last_mode": c.last_mode}


@router.delete("/consultation/{consultation_id}/messages", status_code=204)
def delete_history(consultation_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.clear_history(db, user.id, consultation_id)
    return Response(status_code=204)


@router.post("/consultation/{consultation_id}/escalations")
def escalate(consultation_id: uuid.UUID, body: EscalationBody, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """Demo only: records a simulated nurse-queue request. Nothing is sent."""
    return svc.simulate_escalation(db, user.id, consultation_id, body.category, body.summary)


# ── Patient context ─────────────────────────────────────────────────────


def _ctx_dict(r: PatientContextEntry):
    return {"id": str(r.id), "kind": r.kind, "content": r.content, "provenance": r.provenance,
            "is_synthetic": r.is_synthetic, "source": r.source, "verified_by": r.verified_by,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None}


@router.get("/patient-context")
def list_context(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(PatientContextEntry).filter_by(patient_id=user.id)
            .order_by(PatientContextEntry.created_at.desc()).all())
    return {"entries": [_ctx_dict(r) for r in rows]}


@router.post("/patient-context")
def add_context(body: ContextBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Patients may add their own notes; they are always stored as patient_reported."""
    p = svc.get_program(db)
    m = svc.get_membership(db, user.id, p)
    if m is None or m.care_role != "patient":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the patient can add to their own context")
    r = PatientContextEntry(id=uuid.uuid4(), patient_id=user.id, program_id=p.id, kind=body.kind[:40],
                            content=body.content[:2000], provenance="patient_reported", source="patient (in app)")
    db.add(r)
    db.commit()
    return _ctx_dict(r)


@router.post("/patient-context/demo-seed")
def seed_demo_context(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Adds the KB §8 synthetic record (clearly flagged synthetic) to the caller's own context."""
    p = svc.get_program(db)
    m = svc.get_membership(db, user.id, p)
    if m is None or m.care_role != "patient":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Demo records are only added for patients")
    if db.query(PatientContextEntry).filter_by(patient_id=user.id, is_synthetic=True).count():
        return list_context(db, user)
    for kind, content in (
        ("treatment_stage", "Stimulation — active (synthetic demo record, Harbor Fertility Center)."),
        ("medication_schedule", "NOT POPULATED — no medication schedule on file. Do not infer doses or times."),
        ("clinic_instruction", "Trigger schedule NOT POPULATED. Clinic urgent line: demo only, no number."),
    ):
        db.add(PatientContextEntry(id=uuid.uuid4(), patient_id=user.id, program_id=p.id, kind=kind, content=content,
                                   provenance="verified_clinical", is_synthetic=True,
                                   source="IVF KB §8 synthetic demo record", verified_by="SYNTHETIC — not a clinician"))
    db.commit()
    return list_context(db, user)


# ── Knowledge ───────────────────────────────────────────────────────────


@router.post("/knowledge/ingest-kb")
def ingest_kb(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _clinic_admin(user)
    return knowledge.ingest_kb(db)


@router.post("/knowledge/documents")
def add_knowledge(body: KnowledgeDocBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _clinic_admin(user)
    if body.approval_status == "approved" and (user.role or "") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can mark a source approved")
    return knowledge.ingest_text_document(db, title=body.title, text=body.text, source_type=body.source_type,
                                          approval_status=body.approval_status, clinic_id=body.clinic_id,
                                          audience=body.audience, topic=body.topic, version=body.version)


@router.get("/knowledge/documents")
def list_knowledge(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _clinic_admin(user)
    docs = db.query(FertilityKnowledgeDocument).order_by(FertilityKnowledgeDocument.created_at).all()
    out = []
    for d in docs:
        n = db.query(FertilityKnowledgeChunk).filter_by(document_id=d.id).count()
        e = db.query(FertilityKnowledgeChunk).filter(FertilityKnowledgeChunk.document_id == d.id,
                                                     FertilityKnowledgeChunk.embedding.isnot(None)).count()
        out.append({"id": str(d.id), "key": d.document_key, "title": d.title, "source_type": d.source_type,
                    "approval_status": d.approval_status, "version": d.version, "chunks": n, "embedded_chunks": e})
    return {"documents": out, "knowledge_phase": knowledge.knowledge_phase()}


@router.get("/knowledge/search")
def search_knowledge(q: str, role: str = "patient", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    hits = knowledge.retrieve(db, q, role=role if role in doctor.CARE_ROLES else "patient")
    return {"results": [{**knowledge.source_citation(h, i + 1), "score": h["score"], "content": h["content"]}
                        for i, h in enumerate(hits)]}


# ── Instructional videos ────────────────────────────────────────────────


def _sign(video_id: str, exp: int) -> str:
    return hmac.new(settings.secret_key.encode(), f"video:{video_id}:{exp}".encode(), hashlib.sha256).hexdigest()


def _video_dict(v: InstructionalVideo, segments: int = 0):
    return {"id": str(v.id), "title": v.title, "description": v.description, "topic": v.topic,
            "treatment_stage": v.treatment_stage, "audience": v.audience, "medication_name": v.medication_name,
            "device_name": v.device_name, "language": v.language, "clinic_id": v.clinic_id,
            "approval_status": v.approval_status, "version": v.version, "has_file": bool(v.storage_uri),
            "external_url": v.external_url, "has_transcript": bool(v.transcript), "transcript_segments": segments,
            "duration_seconds": v.duration_seconds,
            "uploaded_at": v.created_at.isoformat() + "Z" if v.created_at else None}


def _visible_videos(db: Session, user: User):
    # Legacy endpoints only ever see legacy (program-less) videos; care-platform
    # videos are tenant-scoped and served by /api/care.
    q = db.query(InstructionalVideo).filter(InstructionalVideo.program_id.is_(None))
    if (user.role or "") not in CLINIC_ADMIN_ROLES:
        q = q.filter(InstructionalVideo.approval_status.in_(knowledge.allowed_approval_statuses()))
    return q


@router.get("/videos")
def list_videos(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    vids = _visible_videos(db, user).order_by(InstructionalVideo.created_at.desc()).all()
    out = []
    for v in vids:
        n = db.query(FertilityKnowledgeChunk).filter_by(video_id=v.id).count()
        out.append(_video_dict(v, n))
    return {"videos": out}


@router.post("/videos")
async def upload_video(
    title: str = Form(...), description: str = Form(""), topic: str = Form(""), treatment_stage: str = Form(""),
    audience: str = Form("both"), medication_name: str = Form(""), device_name: str = Form(""),
    language: str = Form("en"), clinic_id: str = Form("demo-harbor"), approval_status: str = Form("demo_unreviewed"),
    version: str = Form("1"), transcript: str = Form(""), external_url: str = Form(""),
    file: Optional[UploadFile] = File(None), transcript_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    _clinic_admin(user)
    if approval_status == "approved" and (user.role or "") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can mark a video approved")
    if audience not in ("patient", "partner", "both"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "audience must be patient, partner or both")
    v = InstructionalVideo(id=uuid.uuid4(), title=title[:255], description=description or None, topic=topic or None,
                           treatment_stage=treatment_stage or None, audience=audience,
                           medication_name=medication_name.strip() or None, device_name=device_name.strip() or None,
                           language=language or "en", clinic_id=clinic_id or None, approval_status=approval_status,
                           version=version or None, external_url=external_url or None, uploaded_by=user.id)
    if file is not None and file.filename:
        data = await file.read()
        if len(data) > MAX_VIDEO_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Video is larger than 500 MB")
        if not (file.content_type or "").startswith("video/"):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a video file")
        from app.services.private_storage import get_private_storage

        stored = get_private_storage().save(data, kind="fertility-videos", owner="ivf-care",
                                            filename=file.filename, content_type=file.content_type)
        v.storage_uri, v.content_type = stored.uri, file.content_type
    text = transcript
    if transcript_file is not None and transcript_file.filename:
        text = (await transcript_file.read()).decode("utf-8", errors="replace")
    v.transcript = text or None
    if text and ("-->" in text):
        v.captions_vtt = text if text.lstrip().startswith("WEBVTT") else None
    if not v.storage_uri and not v.external_url:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Provide a video file or a URL")
    db.add(v)
    db.commit()
    n = knowledge.index_video_transcript(db, v) if v.transcript else 0
    return _video_dict(v, n)


@router.get("/videos/{video_id}")
def get_video(video_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    v = _visible_videos(db, user).filter(InstructionalVideo.id == video_id).first()
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    segs = (db.query(FertilityKnowledgeChunk).filter_by(video_id=v.id)
            .order_by(FertilityKnowledgeChunk.start_seconds).all())
    d = _video_dict(v, len(segs))
    d["segments"] = [{"start_seconds": s.start_seconds, "end_seconds": s.end_seconds, "text": s.content} for s in segs]
    return d


@router.get("/videos/{video_id}/playback")
def playback_url(video_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Short-lived signed URL; private files are never exposed at a public storage URL."""
    v = _visible_videos(db, user).filter(InstructionalVideo.id == video_id).first()
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    if not v.storage_uri:
        return {"url": v.external_url, "expires_at": None}
    exp = int(time.time()) + PLAYBACK_TTL_S
    base = str(request.base_url).rstrip("/")
    return {"url": f"{base}/api/fertility/videos/{v.id}/stream?exp={exp}&sig={_sign(str(v.id), exp)}",
            "expires_at": datetime.utcfromtimestamp(exp).isoformat() + "Z"}


@router.get("/videos/{video_id}/stream")
def stream_video(video_id: uuid.UUID, exp: int, sig: str, request: Request, db: Session = Depends(get_db)):
    if exp < time.time() or not hmac.compare_digest(sig, _sign(str(video_id), exp)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Playback link expired or invalid")
    v = db.query(InstructionalVideo).filter(InstructionalVideo.id == video_id).first()
    if not v or not v.storage_uri:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    from app.services.private_storage import get_private_storage

    data = get_private_storage().read(v.storage_uri)
    size = len(data)
    ctype = v.content_type or "video/mp4"
    rng = request.headers.get("range")
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, no-store"}
    if rng and rng.startswith("bytes="):
        start_s, _, end_s = rng[6:].partition("-")
        start = int(start_s or 0)
        end = min(int(end_s) if end_s else size - 1, size - 1)
        if start >= size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return Response(data[start:end + 1], status_code=206, media_type=ctype, headers=headers)
    return Response(data, media_type=ctype, headers=headers)


@router.delete("/videos/{video_id}", status_code=204)
def delete_video(video_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _clinic_admin(user)
    v = (db.query(InstructionalVideo)
         .filter(InstructionalVideo.id == video_id, InstructionalVideo.program_id.is_(None)).first())
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    uri = v.storage_uri
    db.query(FertilityKnowledgeDocument).filter_by(document_key=f"video-{v.id}").delete()
    db.delete(v)
    db.commit()
    if uri:
        from app.services.private_storage import get_private_storage

        get_private_storage().delete_quietly(uri)
    return Response(status_code=204)
