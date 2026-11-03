"""HTTP endpoints for Part 3 (clinician review) and Part 4 (care memory, agent grants, agent tools)."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import CareContentItem, CareHandoff, CareReplyDraft, User
from app.dependencies.auth import get_current_user
from app.services.care import access as acl
from app.services.care import agent_access as agents
from app.services.care import clinician_review as cr

router = APIRouter(prefix="/api/care", tags=["care-review-agents"])


# ───────────── Part 3: staff review queue ─────────────
class DraftBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class ApproveBody(BaseModel):
    sha256: str = Field(..., min_length=64, max_length=64)


def _draft(db, draft_id) -> CareReplyDraft:
    d = db.query(CareReplyDraft).filter_by(id=draft_id).first()
    if not d:
        raise acl.not_found()
    return d


@router.get("/review/clinics/{clinic_id}/review-queue")
def review_queue(clinic_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return cr.queue(db, user, clinic_id)


@router.post("/review/requests/{request_id}/drafts", status_code=201)
def create_draft(request_id: uuid.UUID, body: DraftBody, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    h = db.query(CareHandoff).filter_by(id=request_id).first()
    if not h:
        raise acl.not_found()
    return cr.create_draft(db, user, h, body.body)


@router.patch("/review/drafts/{draft_id}")
def edit_draft(draft_id: uuid.UUID, body: DraftBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return cr.edit_draft(db, user, _draft(db, draft_id), body.body)


@router.post("/review/drafts/{draft_id}/approve")
def approve_draft(draft_id: uuid.UUID, body: ApproveBody, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return cr.approve_draft(db, user, _draft(db, draft_id), body.sha256)


@router.post("/review/drafts/{draft_id}/send")
def send_draft(draft_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return cr.send_draft(db, user, _draft(db, draft_id))


@router.post("/review/content/{item_id}/clinician-approve")
def clinician_approve(item_id: uuid.UUID, body: ApproveBody, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    it = db.query(CareContentItem).filter_by(id=item_id).first()
    if not it or not acl.staff_row(db, user, it.clinic_id):
        raise acl.not_found()
    return cr.approve_material(db, user, it, body.sha256)


class GuidanceBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    persona_id: Optional[uuid.UUID] = None


@router.get("/review/clinics/{clinic_id}/doctor-guidance")
def get_guidance(clinic_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    acl.require_staff(db, user, clinic_id, "can_view_clinical")
    return {"text": agents.guidance_get(db, clinic_id)}


@router.put("/review/clinics/{clinic_id}/doctor-guidance")
def put_guidance(clinic_id: uuid.UUID, body: GuidanceBody, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return agents.guidance_set(db, user, clinic_id, body.text, body.persona_id)


# ───────────── Part 4: patient memory and agent grants ─────────────
class MemoryBody(BaseModel):
    value: str = Field(..., min_length=1, max_length=500)


class GrantBody(BaseModel):
    agent_label: str = Field(..., min_length=1, max_length=120)
    scopes: List[str]
    ttl_days: int = 30


@router.get("/c/{clinic_slug}/memory")
def memory(clinic_slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    clinic = agents.patient_clinic(db, user, clinic_slug)
    return {"items": agents.memory_list(db, user, clinic), "keys": agents.MEMORY_KEYS}


@router.put("/c/{clinic_slug}/memory/{key}")
def memory_set(clinic_slug: str, key: str, body: MemoryBody, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    return {"items": agents.memory_set(db, user, agents.patient_clinic(db, user, clinic_slug), key, body.value)}


@router.delete("/c/{clinic_slug}/memory/{key}")
def memory_delete(clinic_slug: str, key: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": agents.memory_delete(db, user, agents.patient_clinic(db, user, clinic_slug), key)}


@router.get("/c/{clinic_slug}/agent-grants")
def grants(clinic_slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    clinic = agents.patient_clinic(db, user, clinic_slug)
    return {"grants": agents.grant_list(db, user, clinic), "log": agents.access_log(db, user, clinic),
            "scopes": agents.SCOPES}


@router.post("/c/{clinic_slug}/agent-grants", status_code=201)
def grant_create(clinic_slug: str, body: GrantBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return agents.grant_create(db, user, agents.patient_clinic(db, user, clinic_slug), body.agent_label, body.scopes,
                               body.ttl_days)


@router.delete("/c/{clinic_slug}/agent-grants/{grant_id}")
def grant_revoke(clinic_slug: str, grant_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return agents.grant_revoke(db, user, agents.patient_clinic(db, user, clinic_slug), grant_id)


# ───────────── Part 4: agent tools over HTTP (bearer = agent token, not a user session) ─────────────
def _bearer(authorization: Optional[str]) -> Optional[str]:
    return authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else None


@router.get("/agent/v1/preferences")
def agent_preferences(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    return agents.get_my_preferences(db, _bearer(authorization))


@router.get("/agent/v1/conversations")
def agent_conversations(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    return agents.list_my_conversations(db, _bearer(authorization))
