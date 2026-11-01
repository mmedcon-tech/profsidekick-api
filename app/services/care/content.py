"""Versioned clinical content: workflow, indexing and scoped retrieval.

States: draft → in_review → approved → retired. An upload or edit never
publishes. Editing an approved item creates a new draft version in the same
lineage; approving it retires the previous approved version and drops that
version's chunks, so stale text is never retrievable.
Retrieval only returns chunks whose item is approved, unexpired, in the
caller's clinic + program, in a course the caller can see, and for their
audience.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.database.models import CareContentChunk, CareContentItem, CareCourse, User
from app.services.audit_service import record_audit_event

logger = logging.getLogger(__name__)

KINDS = ("protocol", "patient_instruction", "faq", "document", "deidentified_case")
AUDIENCES = ("patient", "caregiver", "both", "staff")
TRANSITIONS = {
    "submit": ("draft", "in_review"),
    "return_to_draft": ("in_review", "draft"),
    "approve": ("in_review", "approved"),
    "retire": ("approved", "retired"),
}


def chunk_text(text: str, max_chars: int = 900) -> List[str]:
    paras = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    out: List[str] = []
    buf = ""
    for p in paras:
        if buf and len(buf) + len(p) + 2 > max_chars:
            out.append(buf)
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
        while len(buf) > max_chars:
            out.append(buf[:max_chars])
            buf = buf[max_chars:]
    if buf:
        out.append(buf)
    return out


def _try_embed(texts: List[str]):
    from app.services.fertility.knowledge import _try_embed as embed

    return embed(texts)


def index_item(db: DBSession, item: CareContentItem) -> int:
    db.query(CareContentChunk).filter_by(item_id=item.id).delete()
    parts = chunk_text(f"{item.title}\n\n{item.body}")
    vecs = _try_embed(parts) or [None] * len(parts)
    for i, (p, v) in enumerate(zip(parts, vecs)):
        db.add(CareContentChunk(id=uuid.uuid4(), item_id=item.id, position=i, content=p, embedding=v))
    return len(parts)


def item_dict(i: CareContentItem) -> Dict[str, Any]:
    return {
        "id": str(i.id), "lineage_id": str(i.lineage_id), "version": i.version, "clinic_id": str(i.clinic_id),
        "program_id": str(i.program_id), "course_id": str(i.course_id) if i.course_id else None, "kind": i.kind,
        "title": i.title, "body": i.body, "language": i.language, "audience": i.audience,
        "applicability": i.applicability, "source": i.source, "status": i.status, "reviewer": i.reviewer,
        "approved_at": i.approved_at.isoformat() if i.approved_at else None,
        "expires_at": i.expires_at.isoformat() if i.expires_at else None, "is_demo": i.is_demo,
        "updated_at": i.updated_at.isoformat() if i.updated_at else None,
    }


def transition(db: DBSession, item: CareContentItem, action: str, actor: User, reviewer: Optional[str] = None) -> CareContentItem:
    if action not in TRANSITIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown action")
    frm, to = TRANSITIONS[action]
    if item.status != frm:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot {action} an item in status {item.status}")
    now = datetime.utcnow()
    if action == "approve":
        if not (reviewer or item.reviewer):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Approval needs the reviewing clinician's name")
        if item.expires_at and item.expires_at <= now:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Expiry date is in the past")
        item.reviewer = reviewer or item.reviewer
        item.approved_by = actor.id
        item.approved_at = now
        # supersede the previous active version in this lineage
        for old in (db.query(CareContentItem)
                    .filter(CareContentItem.lineage_id == item.lineage_id, CareContentItem.id != item.id,
                            CareContentItem.status == "approved").all()):
            old.status = "retired"
            old.updated_at = now
            db.query(CareContentChunk).filter_by(item_id=old.id).delete()
        item.status = to
        index_item(db, item)
    else:
        item.status = to
        if to in ("retired", "draft"):
            db.query(CareContentChunk).filter_by(item_id=item.id).delete()
    item.updated_at = now
    record_audit_event(db, action=f"care_content.{action}", entity_type="care_content_item", entity_id=item.id,
                       actor_user_id=actor.id, data={"version": item.version, "status": item.status,
                                                     "lineage_id": str(item.lineage_id)})
    return item


def new_version(db: DBSession, item: CareContentItem, actor: User, **changes) -> CareContentItem:
    """Edit: drafts change in place; anything else forks a new draft version."""
    now = datetime.utcnow()
    if item.status == "draft":
        for k, v in changes.items():
            setattr(item, k, v)
        item.updated_at = now
        target = item
    else:
        latest = (db.query(CareContentItem).filter_by(lineage_id=item.lineage_id)
                  .order_by(CareContentItem.version.desc()).first())
        target = CareContentItem(
            id=uuid.uuid4(), lineage_id=item.lineage_id, version=latest.version + 1, clinic_id=item.clinic_id,
            program_id=item.program_id, course_id=item.course_id, kind=item.kind, title=item.title, body=item.body,
            language=item.language, audience=item.audience, applicability=item.applicability, source=item.source,
            status="draft", expires_at=item.expires_at, is_demo=item.is_demo, created_by=actor.id,
            created_at=now, updated_at=now)
        for k, v in changes.items():
            setattr(target, k, v)
        db.add(target)
    record_audit_event(db, action="care_content.edit", entity_type="care_content_item", entity_id=target.id,
                       actor_user_id=actor.id, data={"version": target.version, "fields": sorted(changes)})
    return target


def _terms(q: str) -> List[str]:
    from app.services.rag_service import _query_terms

    return _query_terms(q)


def retrieve(db: DBSession, *, program_id, clinic_id, visible_course_ids: Set, audience: str, query: str,
             top_k: int = 4) -> List[Dict[str, Any]]:
    if not (query or "").strip():
        return []
    now = datetime.utcnow()
    aud = ["both", "patient"] if audience == "patient" else ["both", audience]
    base = (db.query(CareContentChunk, CareContentItem)
            .join(CareContentItem, CareContentItem.id == CareContentChunk.item_id)
            .filter(CareContentItem.clinic_id == clinic_id, CareContentItem.program_id == program_id,
                    CareContentItem.status == "approved",
                    or_(CareContentItem.expires_at.is_(None), CareContentItem.expires_at > now),
                    CareContentItem.audience.in_(aud),
                    or_(CareContentItem.course_id.is_(None),
                        CareContentItem.course_id.in_(list(visible_course_ids) or [uuid.uuid4()]))))
    pool: Dict[Any, tuple] = {}
    vec = _try_embed([query])
    if vec:
        dist = CareContentChunk.embedding.cosine_distance(vec[0])
        for ch, it, d in (base.add_columns(dist.label("d")).filter(CareContentChunk.embedding.isnot(None))
                          .order_by(dist).limit(top_k * 4).all()):
            pool[ch.id] = (ch, it, 1.0 - float(d))
    terms = _terms(query)
    if terms:
        for ch, it in base.filter(or_(*[CareContentChunk.content.ilike(f"%{t}%") for t in terms])).limit(100).all():
            frac = sum(1 for t in terms if t in ch.content.lower()) / len(terms)
            score = 0.25 + 0.5 * frac
            if ch.id not in pool or pool[ch.id][2] < score:
                pool[ch.id] = (ch, it, score)
    ranked = sorted(pool.values(), key=lambda x: x[2], reverse=True)
    return [{
        "chunk_id": str(ch.id), "item_id": str(it.id), "content": ch.content, "score": round(s, 3),
        "title": it.title, "kind": it.kind, "version": it.version, "reviewer": it.reviewer,
        "approved_at": it.approved_at.date().isoformat() if it.approved_at else None, "is_demo": it.is_demo,
    } for ch, it, s in ranked if s >= 0.3][:top_k]


def visible_course_ids(db: DBSession, access) -> Set:
    courses = db.query(CareCourse).filter_by(program_id=access.program.id).all()
    return {c.id for c in courses if access.can_see_course(c)}
