"""
Find avatar knowledge documents that have no retrievable chunks and index
them: from the stored file when there is one, otherwise from the typed text.

Documents can be unindexed because they were typed in before typed knowledge
was indexed, or because ingestion failed in the background.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from sqlalchemy.orm import Session

from app.database.models import KnowledgeChunk, KnowledgeDocument
from app.services.private_storage import get_private_storage, is_private_uri
from app.services.rag_service import (
    ingest_avatar_knowledge_document,
    ingest_avatar_knowledge_text,
)

logger = logging.getLogger(__name__)


@dataclass
class IndexReport:
    indexed: List[str] = field(default_factory=list)
    would_index: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


def _source(doc: KnowledgeDocument) -> str:
    return f"avatar_knowledge:{doc.avatar_configuration_id}:{doc.id}"


def find_unindexed(db: Session) -> List[KnowledgeDocument]:
    indexed = {row[0] for row in db.query(KnowledgeChunk.source).distinct().all()}
    return [d for d in db.query(KnowledgeDocument).all() if _source(d) not in indexed]


def _file_bytes(doc: KnowledgeDocument) -> bytes | None:
    if not doc.file_path:
        return None
    try:
        if is_private_uri(doc.file_path):
            return get_private_storage().read(doc.file_path)
        path = Path(doc.file_path)
        return path.read_bytes() if path.is_file() else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not read file for %s: %s", doc.id, exc)
        return None


def index_unindexed(db: Session, *, apply: bool = False) -> IndexReport:
    report = IndexReport()
    for doc in find_unindexed(db):
        label = f"{doc.id} ({doc.title})"
        content = _file_bytes(doc)
        text = (doc.content_text or "").strip()
        if content is None and not text:
            report.skipped.append(f"{label}: no file or text to index")
            continue
        if not apply:
            report.would_index.append(label)
            continue
        if content is not None:
            n = ingest_avatar_knowledge_document(
                doc.id,
                doc.avatar_configuration_id,
                content,
                doc.file_name or "document",
                db,
            )
        else:
            n = ingest_avatar_knowledge_text(
                doc.id, doc.avatar_configuration_id, text, db
            )
        (report.indexed if n else report.skipped).append(
            label if n else f"{label}: no extractable text"
        )
    return report


def embed_missing(db: Session, *, apply: bool = False, batch_size: int = 64) -> int:
    """
    Add embeddings to chunks stored without one (indexed while the embeddings
    API was failing, for example with a missing key). Returns how many chunks
    lack an embedding (dry run) or were embedded (apply).
    """
    from app.database.models import SlideChunk
    from app.services.rag_service import _embed

    done = 0
    for model in (KnowledgeChunk, SlideChunk):
        rows = db.query(model).filter(model.embedding.is_(None)).all()
        if not apply:
            done += len(rows)
            continue
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            vectors = _embed([r.content for r in batch])
            for row, vector in zip(batch, vectors):
                row.embedding = vector
            db.commit()
            done += len(batch)
    return done
