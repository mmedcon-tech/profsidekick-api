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
from app.services.care import integrity

logger = logging.getLogger(__name__)

KINDS = ("protocol", "patient_instruction", "faq", "document", "deidentified_case")
# Created only by sync_video_transcript, never through the content editor.
SYSTEM_KINDS = ("video_transcript",)
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


def invalidate_item(db: DBSession, item_id) -> int:
    """Drop every retrieval artefact of one item version: chunks (keyword
    index) and their embeddings (vector index). There is no other cache of
    care content; answers are never cached."""
    n = db.query(CareContentChunk).filter_by(item_id=item_id).delete(synchronize_session=False)
    if n:
        logger.info("care_content.invalidate item=%s chunks=%s", item_id, n)
    return n


def pin_seeded(item: CareContentItem) -> None:
    """Seed data is created already approved (demo, labelled); pin its hash the same way approval does."""
    assert item.status == "approved" and item.approved_sha256 is None
    item.content_sha256 = item.approved_sha256 = integrity.content_hash(item)


def index_item(db: DBSession, item: CareContentItem) -> int:
    """(Re)build chunks + embeddings for an approved item, tagged with its pinned hash."""
    invalidate_item(db, item.id)
    if item.status != "approved" or not item.approved_sha256:
        return 0
    parts = chunk_text(f"{item.title}\n\n{item.body}")
    vecs = _try_embed(parts) or [None] * len(parts)
    for i, (p, v) in enumerate(zip(parts, vecs)):
        db.add(CareContentChunk(id=uuid.uuid4(), item_id=item.id, position=i, content=p, embedding=v,
                                item_sha256=item.approved_sha256))
    return len(parts)


def item_dict(i: CareContentItem) -> Dict[str, Any]:
    return {
        "id": str(i.id), "lineage_id": str(i.lineage_id), "version": i.version, "clinic_id": str(i.clinic_id),
        "program_id": str(i.program_id), "course_id": str(i.course_id) if i.course_id else None, "kind": i.kind,
        "title": i.title, "body": i.body, "language": i.language, "audience": i.audience,
        "applicability": i.applicability, "source": i.source, "status": i.status, "reviewer": i.reviewer,
        "approved_at": i.approved_at.isoformat() if i.approved_at else None,
        "content_sha256": i.content_sha256, "approved_sha256": i.approved_sha256,
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
            invalidate_item(db, old.id)
        item.content_sha256 = integrity.content_hash(item)
        item.approved_sha256 = item.content_sha256  # pin: what was reviewed is what gets retrieved
        item.status = to
        index_item(db, item)
    else:
        item.status = to
        if to in ("retired", "draft"):
            invalidate_item(db, item.id)
    item.updated_at = now
    record_audit_event(db, action=f"care_content.{action}", entity_type="care_content_item", entity_id=item.id,
                       actor_user_id=actor.id, data={"version": item.version, "status": item.status,
                                                     "lineage_id": str(item.lineage_id),
                                                     "sha256": item.approved_sha256 if action == "approve" else None})
    return item


def new_version(db: DBSession, item: CareContentItem, actor: User, **changes) -> CareContentItem:
    """Edit: drafts change in place; anything else forks a new draft version."""
    now = datetime.utcnow()
    if item.status == "draft":
        for k, v in changes.items():
            setattr(item, k, v)
        item.updated_at = now
        item.content_sha256 = integrity.content_hash(item)
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
        target.content_sha256 = integrity.content_hash(target)
        db.add(target)
    record_audit_event(db, action="care_content.edit", entity_type="care_content_item", entity_id=target.id,
                       actor_user_id=actor.id, data={"version": target.version, "fields": sorted(changes)})
    return target


def _terms(q: str) -> List[str]:
    from app.services.rag_service import _query_terms

    return _query_terms(q)


def retrieve(db: DBSession, *, program_id, clinic_id, visible_course_ids: Set, audience: str, query: str,
             top_k: int = 4, lineage_ids: Optional[List] = None) -> List[Dict[str, Any]]:
    if not (query or "").strip():
        return []
    now = datetime.utcnow()
    aud = ["both", "patient"] if audience == "patient" else ["both", audience]
    base = (db.query(CareContentChunk, CareContentItem)
            .join(CareContentItem, CareContentItem.id == CareContentChunk.item_id)
            .filter(CareContentItem.clinic_id == clinic_id, CareContentItem.program_id == program_id,
                    CareContentItem.status == "approved",
                    CareContentItem.approved_sha256.isnot(None),
                    CareContentChunk.item_sha256 == CareContentItem.approved_sha256,
                    or_(CareContentItem.expires_at.is_(None), CareContentItem.expires_at > now),
                    CareContentItem.audience.in_(aud),
                    or_(CareContentItem.course_id.is_(None),
                        CareContentItem.course_id.in_(list(visible_course_ids) or [uuid.uuid4()]))))
    if lineage_ids:
        base = base.filter(CareContentItem.lineage_id.in_(lineage_ids))
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
    ranked = []
    for r in sorted(pool.values(), key=lambda x: x[2], reverse=True):
        if r[2] < 0.3:
            break
        if not integrity.verify(r[1]):  # row changed outside the workflow: never serve it
            logger.warning("care_content.hash_mismatch item=%s v%s - excluded from retrieval", r[1].id, r[1].version)
            continue
        ranked.append(r)
        if len(ranked) >= top_k:
            break
    counts: Dict[Any, int] = {}
    if ranked:
        from sqlalchemy import func

        ids = list({it.id for _, it, _ in ranked})
        counts = dict(db.query(CareContentChunk.item_id, func.count(CareContentChunk.id))
                      .filter(CareContentChunk.item_id.in_(ids)).group_by(CareContentChunk.item_id).all())
    return [{
        "chunk_id": str(ch.id), "item_id": str(it.id), "content": ch.content, "score": round(s, 3),
        "title": it.title, "kind": it.kind, "version": it.version, "reviewer": it.reviewer,
        "approved_at": it.approved_at.date().isoformat() if it.approved_at else None, "is_demo": it.is_demo,
        "sha256": it.approved_sha256, "segment": ch.position + 1, "segments": max(counts.get(it.id, 1), ch.position + 1),
        "video_id": str(it.video_id) if it.video_id else None,
    } for ch, it, s in ranked]


def visible_course_ids(db: DBSession, access) -> Set:
    courses = db.query(CareCourse).filter_by(program_id=access.program.id).all()
    return {c.id for c in courses if access.can_see_course(c)}


def sync_video_transcript(db: DBSession, video, actor: User) -> Optional[CareContentItem]:
    """Video transcripts follow the video's own review lifecycle: the transcript
    becomes retrievable only when the video is approved (same reviewer, same
    date), and is retired with it. Re-approval creates a new version."""
    if not video.program_id:
        return None
    from app.database.models import CareProgram

    prog = db.query(CareProgram).filter_by(id=video.program_id).first()
    current = (db.query(CareContentItem).filter_by(video_id=video.id)
               .order_by(CareContentItem.version.desc()).first())
    now = datetime.utcnow()
    if video.status != "approved" or not (video.transcript or "").strip():
        if current and current.status == "approved":
            current.status = "retired"
            current.updated_at = now
            invalidate_item(db, current.id)
        return current
    if current and current.status == "approved" and current.body == video.transcript and integrity.verify(current):
        return current
    if current and current.status == "approved":
        current.status = "retired"
        invalidate_item(db, current.id)
    item = CareContentItem(
        id=uuid.uuid4(), lineage_id=current.lineage_id if current else uuid.uuid4(),
        version=(current.version + 1) if current else 1, clinic_id=prog.clinic_ref_id, program_id=prog.id,
        course_id=video.course_id, kind="video_transcript", title=f"Video transcript: {video.title}",
        body=video.transcript, language=video.language or "en", audience="both", source="Approved video transcript",
        status="approved", reviewer=video.reviewer, approved_by=actor.id if actor else None,
        approved_at=video.approved_at or now, is_demo=bool(getattr(prog, "is_demo", False)), video_id=video.id,
        created_by=actor.id if actor else None, created_at=now, updated_at=now)
    item.content_sha256 = item.approved_sha256 = integrity.content_hash(item)
    db.add(item)
    db.flush()
    index_item(db, item)
    return item
