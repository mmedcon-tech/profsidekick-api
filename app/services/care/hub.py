"""Clinic Knowledge Hub: portable export of a clinic's documents + metadata, and a reindex that
rebuilds the search index when the embedding model changes. Same service layer for website,
API, scripts and (future) MCP tools. Patient Care Context is never part of an export."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.database.models import CareContentChunk, CareContentItem, CareProgram, Clinic

EXPORT_FORMAT = "myos.clinic-knowledge.v1"
_FIELDS = ("lineage_id", "version", "kind", "title", "body", "language", "audience", "applicability", "source",
           "source_url", "source_type", "status", "reviewer", "approved_at", "expires_at", "effective_from",
           "effective_to", "is_demo", "content_sha256", "approved_sha256", "created_at", "updated_at")


def _v(x):
    if isinstance(x, datetime):
        return x.isoformat()
    return str(x) if x is not None and not isinstance(x, (str, int, bool, float)) else x


def export_clinic(db: DBSession, clinic: Clinic, include_drafts: bool = False) -> Dict[str, Any]:
    """Every version (history) of every document, with approval and source metadata.
    No embeddings (model-specific, rebuilt by reindex) and no patient data."""
    progs = db.query(CareProgram).filter_by(clinic_ref_id=clinic.id).all()
    out: List[Dict[str, Any]] = []
    for p in progs:
        q = db.query(CareContentItem).filter_by(clinic_id=clinic.id, program_id=p.id)
        if not include_drafts:
            q = q.filter(CareContentItem.status.in_(("approved", "in_review", "retired")))
        for it in q.order_by(CareContentItem.lineage_id, CareContentItem.version).all():
            d = {f: _v(getattr(it, f)) for f in _FIELDS}
            d["program"] = p.slug
            d["approved_by_recorded"] = it.approved_by is not None
            out.append(d)
    doc = {"format": EXPORT_FORMAT, "clinic": {"slug": clinic.slug, "name": clinic.name, "languages": clinic.languages},
           "exported_at": datetime.utcnow().isoformat(), "items": out}
    doc["digest"] = hashlib.sha256(repr(sorted((i["lineage_id"], i["version"], i["content_sha256"]) for i in out))
                                   .encode()).hexdigest()
    return doc


def reindex(db: DBSession, clinic: Optional[Clinic] = None, force: bool = False, batch: int = 128) -> Dict[str, Any]:
    """Re-embed every chunk whose vector was made by a different (or no) model than the active one.
    Keyword search keeps working throughout; vectors from the old model are never mixed in retrieval."""
    from app.services.ai import router
    from app.services.fertility.knowledge import _try_embed

    active = router.active_embedding_model(clinic)
    q = db.query(CareContentChunk).join(CareContentItem, CareContentItem.id == CareContentChunk.item_id)
    if clinic is not None:
        q = q.filter(CareContentItem.clinic_id == clinic.id)
    if not force:
        q = q.filter((CareContentChunk.embedding_model.is_(None)) | (CareContentChunk.embedding_model != active))
    rows = q.all()
    done = failed = 0
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        vecs = _try_embed([r.content for r in part])
        if not vecs:
            failed += len(part)
            continue
        for r, v in zip(part, vecs):
            r.embedding, r.embedding_model = v, active
        done += len(part)
        db.commit()
    return {"active_model": active, "candidates": len(rows), "reembedded": done, "failed": failed}
