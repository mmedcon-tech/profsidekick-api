"""Part 3: clinician review in the staff inbox.

Reply drafts move awaiting_review -> reviewed -> sent; the three states are never merged.
"Clinician-approved" is shown only when a clinician (clinic staff with can_approve) recorded an
approval of the exact sha256 of the text being shown, with who and when. Any edit changes the hash
and the draft returns to awaiting_review; a draft can only be sent while its approval still matches.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.database.models import (CareClinicianApproval, CareContentItem, CareHandoff, CareReplyDraft, ClinicStaff,
                                 User)
from app.services.audit_service import record_audit_event
from app.services.care import access as acl
from app.services.care import content, integrity, review

AWAITING, REVIEWED, SENT = "awaiting_review", "reviewed", "sent"
STATE_LABEL = {AWAITING: "Awaiting review", REVIEWED: "Reviewed", SENT: "Sent"}


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _clinician_name(db, user: User, clinic_id) -> str:
    row = db.query(ClinicStaff).filter_by(clinic_id=clinic_id, user_id=user.id).first()
    return (row.display_name if row and row.display_name else
            f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username)


def _record(db, clinic_id, subject_type, subject_id, digest, user: User) -> CareClinicianApproval:
    a = CareClinicianApproval(id=uuid.uuid4(), clinic_id=clinic_id, subject_type=subject_type, subject_id=subject_id,
                              sha256=digest, approver_user_id=user.id,
                              approver_name=_clinician_name(db, user, clinic_id), approved_at=datetime.utcnow())
    db.add(a)
    return a


def approval_for(db, subject_type: str, subject_id, digest: Optional[str]) -> Optional[CareClinicianApproval]:
    if not digest:
        return None
    return (db.query(CareClinicianApproval)
            .filter_by(subject_type=subject_type, subject_id=subject_id, sha256=digest)
            .order_by(CareClinicianApproval.approved_at.desc()).first())


def _approval_dict(a: Optional[CareClinicianApproval]) -> Optional[Dict[str, Any]]:
    return {"by": a.approver_name, "at": a.approved_at.isoformat() + "Z", "sha256": a.sha256} if a else None


# ── reply drafts ──
def draft_view(db, d: CareReplyDraft) -> Dict[str, Any]:
    appr = approval_for(db, "reply_draft", d.id, d.body_sha256) if d.state in (REVIEWED, SENT) else None
    return {"id": str(d.id), "handoff_id": str(d.handoff_id), "body": d.body, "sha256": d.body_sha256,
            "state": d.state, "state_label": STATE_LABEL[d.state],
            "clinician_approved": appr is not None, "approval": _approval_dict(appr),
            "sent_at": d.sent_at.isoformat() + "Z" if d.sent_at else None}


def create_draft(db: DBSession, actor: User, h: CareHandoff, body: str) -> Dict[str, Any]:
    acl.require_staff(db, actor, h.clinic_id, "can_view_clinical")
    body = (body or "").strip()
    if not body:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Draft is empty")
    if h.status == "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Request is closed")
    d = CareReplyDraft(id=uuid.uuid4(), clinic_id=h.clinic_id, handoff_id=h.id, body=body[:4000],
                       body_sha256=sha(body[:4000]), state=AWAITING, author_user_id=actor.id, created_at=datetime.utcnow())
    db.add(d)
    record_audit_event(db, action="care.draft_created", entity_type="care_reply_draft", entity_id=d.id,
                       actor_user_id=actor.id, data={"handoff_id": str(h.id)})
    db.commit()
    return draft_view(db, d)


def edit_draft(db: DBSession, actor: User, d: CareReplyDraft, body: str) -> Dict[str, Any]:
    acl.require_staff(db, actor, d.clinic_id, "can_view_clinical")
    if d.state == SENT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Draft was already sent")
    body = (body or "").strip()[:4000]
    if not body:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Draft is empty")
    if sha(body) != d.body_sha256:
        d.body, d.body_sha256, d.state = body, sha(body), AWAITING  # any edit needs a fresh review
    d.updated_at = datetime.utcnow()
    db.commit()
    return draft_view(db, d)


def approve_draft(db: DBSession, actor: User, d: CareReplyDraft, reviewed_sha256: str) -> Dict[str, Any]:
    acl.require_staff(db, actor, d.clinic_id, "can_approve")
    if d.state == SENT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Draft was already sent")
    if reviewed_sha256 != d.body_sha256:
        raise HTTPException(status.HTTP_409_CONFLICT, "The draft changed since you opened it; review the current text")
    _record(db, d.clinic_id, "reply_draft", d.id, d.body_sha256, actor)
    d.state, d.updated_at = REVIEWED, datetime.utcnow()
    record_audit_event(db, action="care.draft_reviewed", entity_type="care_reply_draft", entity_id=d.id,
                       actor_user_id=actor.id, data={"sha256": d.body_sha256})
    db.commit()
    return draft_view(db, d)


def send_draft(db: DBSession, actor: User, d: CareReplyDraft) -> Dict[str, Any]:
    acl.require_staff(db, actor, d.clinic_id, "can_view_clinical")
    if d.state == SENT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Draft was already sent")
    if d.state != REVIEWED or approval_for(db, "reply_draft", d.id, d.body_sha256) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A clinician must review this exact text before it is sent")
    h = db.query(CareHandoff).filter_by(id=d.handoff_id).first()
    review.staff_action(db, actor, h, "reply", d.body)
    d.state, d.sent_at, d.sent_by, d.updated_at = SENT, datetime.utcnow(), actor.id, datetime.utcnow()
    db.commit()
    return draft_view(db, d)


# ── material (clinic content) ──
def material_view(db, it: CareContentItem) -> Dict[str, Any]:
    appr = approval_for(db, "content_item", it.id, it.approved_sha256) if it.status == "approved" else None
    return {"id": str(it.id), "title": it.title, "kind": it.kind, "version": it.version, "status": it.status,
            "status_label": content.status_label(it), "sha256": integrity.content_hash(it), "body": it.body,
            "clinician_approved": appr is not None, "approval": _approval_dict(appr)}


def approve_material(db: DBSession, actor: User, it: CareContentItem, reviewed_sha256: str) -> Dict[str, Any]:
    acl.require_staff(db, actor, it.clinic_id, "can_approve")
    if it.kind in content.SYSTEM_KINDS:
        raise HTTPException(status.HTTP_409_CONFLICT, "Video transcripts follow the video's review; act on the video")
    current = integrity.content_hash(it)
    if reviewed_sha256 != current:
        raise HTTPException(status.HTTP_409_CONFLICT, "This material changed since you opened it; review the current version")
    content.transition(db, it, "approve", actor, _clinician_name(db, actor, it.clinic_id))
    _record(db, it.clinic_id, "content_item", it.id, it.approved_sha256, actor)
    db.commit()
    return material_view(db, it)


def queue(db: DBSession, actor: User, clinic_id) -> Dict[str, List[Dict[str, Any]]]:
    acl.require_staff(db, actor, clinic_id, "can_view_clinical")
    drafts = (db.query(CareReplyDraft).filter_by(clinic_id=clinic_id)
              .order_by(CareReplyDraft.created_at.desc()).limit(200).all())
    items = (db.query(CareContentItem).filter_by(clinic_id=clinic_id, status="in_review")
             .order_by(CareContentItem.updated_at.desc()).limit(200).all())
    return {"drafts": [draft_view(db, d) for d in drafts], "material": [material_view(db, i) for i in items]}
