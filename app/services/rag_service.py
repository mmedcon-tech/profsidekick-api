"""
RAG (Retrieval-Augmented Generation) service.

Responsibilities:
  1. ``ingest_session_document`` — chunk slide text, embed each chunk with
     OpenAI text-embedding-3-small, and store SlideChunk rows.
  2. ``ingest_course_material`` — extract text from an uploaded course material
     file (PDF / PPTX), chunk, embed, and store KnowledgeChunk rows scoped to
     the course.  Called by ``CourseMaterialService.upload_material_file``.
  3. ``retrieve_context`` — cosine-similarity search against SlideChunk rows
     (session-scoped) AND KnowledgeChunk rows (course-scoped), returning the
     top-k most relevant text chunks for a given query.
  4. ``build_grounded_prompt`` — assembles the final context block that is
     injected into the OpenAI Realtime / Chat Completions system prompt.

Embedding model: text-embedding-3-small (1536 dimensions, $0.02 / 1M tokens).
Chunking strategy: ~400-token windows with 50-token overlap (character-based
approximation: 1 token ≈ 4 characters → ~1 600 chars per chunk, 200-char overlap).
"""

from __future__ import annotations

import io
import re
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.database.connection import SessionLocal
from app.database.models import KnowledgeChunk, KnowledgeDocument, SlideChunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chunking constants
# ---------------------------------------------------------------------------

_CHARS_PER_CHUNK = 1_600  # ≈ 400 tokens at 4 chars/token
_CHARS_OVERLAP = 200  # ≈ 50 tokens of overlap between consecutive chunks

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


def _embed(texts: List[str]) -> List[List[float]]:
    """
    Call the OpenAI Embeddings API and return a list of 1536-dim vectors.

    Uses the ``openai`` client already initialised in ``openai_service.py``.
    Batches up to 2 048 texts per API call (OpenAI hard limit).
    """
    from openai import OpenAI  # lazy import — avoids module-level side effects

    client = OpenAI(api_key=settings.openai_api_key)

    all_vectors: List[List[float]] = []
    batch_size = 512  # stay well under the 2 048 limit

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=batch,
        )
        all_vectors.extend([item.embedding for item in response.data])

    return all_vectors


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_text(text_content: str) -> List[str]:
    """
    Split ``text_content`` into overlapping character windows.

    Returns a list of non-empty string chunks.
    """
    if not text_content or not text_content.strip():
        return []

    chunks: List[str] = []
    start = 0
    length = len(text_content)

    while start < length:
        end = min(start + _CHARS_PER_CHUNK, length)
        chunk = text_content[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start += _CHARS_PER_CHUNK - _CHARS_OVERLAP

    return chunks


# ---------------------------------------------------------------------------
# Text extraction from uploaded files
# ---------------------------------------------------------------------------


def _extract_text_from_content(file_content: bytes, filename: str) -> str:
    """
    Extract plain text from the bytes of a PDF or PPTX file.

    Returns an empty string if the file type is unsupported or extraction fails.
    Works entirely in memory — no temp files written.
    """
    suffix = (filename or "").rsplit(".", 1)[-1].lower()

    if suffix == "pdf":
        try:
            import PyPDF2  # type: ignore

            reader = PyPDF2.PdfReader(io.BytesIO(file_content))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(p for p in pages if p.strip())
        except Exception as exc:
            logger.warning("PDF text extraction failed for %s: %s", filename, exc)
            return ""

    if suffix in ("pptx", "ppt"):
        try:
            from pptx import Presentation  # type: ignore

            prs = Presentation(io.BytesIO(file_content))
            slide_texts = []
            for i, slide in enumerate(prs.slides, 1):
                texts = [
                    shape.text.strip()
                    for shape in slide.shapes
                    if hasattr(shape, "text") and shape.text.strip()
                ]
                if texts:
                    slide_texts.append(f"[Slide {i}]\n" + "\n".join(texts))
            return "\n\n".join(slide_texts)
        except Exception as exc:
            logger.warning("PPTX text extraction failed for %s: %s", filename, exc)
            return ""

    if suffix in ("docx", "doc"):
        try:
            from docx import Document as DocxDocument  # type: ignore

            doc = DocxDocument(io.BytesIO(file_content))
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
        except Exception as exc:
            logger.warning("DOCX text extraction failed for %s: %s", filename, exc)
            return ""

    # Attempt UTF-8 plain-text read for .txt / .md / other text files.
    try:
        return file_content.decode("utf-8", errors="ignore")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Course-material ingestion
# ---------------------------------------------------------------------------


def ingest_course_material(
    course_id: uuid.UUID,
    material_id: uuid.UUID,
    file_content: bytes,
    file_name: str,
    db: DBSession,
) -> int:
    """
    Extract text from a course material file, chunk, embed, and persist as
    ``KnowledgeChunk`` rows scoped to ``course_id``.

    Existing chunks for this specific material are deleted first so that
    re-uploads don't accumulate stale embeddings.

    Returns the number of chunks stored (0 if no text could be extracted).
    """
    source_tag = f"course_material:{str(material_id)}"

    # Remove stale chunks from a previous upload of the same material.
    db.query(KnowledgeChunk).filter(
        KnowledgeChunk.course_id == course_id,
        KnowledgeChunk.source == source_tag,
    ).delete()

    raw_text = _extract_text_from_content(file_content, file_name)
    if not raw_text.strip():
        logger.info(
            "ingest_course_material: no text extracted from %s (material %s)",
            file_name,
            material_id,
        )
        db.commit()  # persist the stale-chunk deletion
        return 0

    raw_chunks = _chunk_text(raw_text)
    if not raw_chunks:
        db.commit()
        return 0

    try:
        vectors = _embed(raw_chunks)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "ingest_course_material: embedding failed for material %s — %s",
            material_id,
            exc,
        )
        vectors = [None] * len(raw_chunks)  # type: ignore[list-item]

    rows: List[KnowledgeChunk] = [
        KnowledgeChunk(
            id=uuid.uuid4(),
            course_id=course_id,
            session_id=None,
            source=source_tag,
            content=chunk,
            embedding=vector,
        )
        for chunk, vector in zip(raw_chunks, vectors)
    ]

    db.add_all(rows)
    db.commit()

    logger.info(
        "ingest_course_material: stored %d chunks for course %s material %s",
        len(rows),
        course_id,
        material_id,
    )
    return len(rows)


def ingest_course_material_background(
    course_id: uuid.UUID,
    material_id: uuid.UUID,
    file_content: bytes,
    file_name: str,
) -> None:
    """
    Background-task wrapper for course-material ingestion.

    FastAPI request-scoped DB sessions are closed before/around background
    execution, so this task owns a fresh session for the ingestion transaction.
    """
    db = SessionLocal()
    try:
        ingest_course_material(course_id, material_id, file_content, file_name, db)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Background RAG ingestion failed for course material %s: %s",
            material_id,
            exc,
        )
        db.rollback()
    finally:
        db.close()


def ingest_session_document(
    session_id: uuid.UUID,
    slides: List[Dict[str, Any]],
    db: DBSession,
) -> int:
    """
    Chunk and embed text extracted from ``slides``, then persist ``SlideChunk``
    rows for the given ``session_id``.

    ``slides`` is the list of slide dicts already produced by
    ``file_processor.py`` — each dict must contain at least:
      - ``slideNumber`` (int)
      - ``content`` (str)  ← extracted text

    Returns the number of chunks stored.

    Existing chunks for the session are deleted first so that re-uploads do
    not accumulate stale embeddings.
    """
    # Delete stale chunks from previous uploads.
    db.query(SlideChunk).filter(SlideChunk.session_id == session_id).delete()

    all_chunks: List[Dict[str, Any]] = []

    for slide in slides:
        # Solution slides are internal grading references (context_builder
        # marks them "never reveal"); they must not be retrievable by learners.
        if slide.get("source") == "solution":
            continue
        slide_number = slide.get("slideNumber") or slide.get("slide_number", 0)
        content = slide.get("content", "")
        if not content or not content.strip():
            continue

        for idx, chunk_text in enumerate(_chunk_text(content)):
            all_chunks.append(
                {
                    "slide_number": slide_number,
                    "chunk_index": idx,
                    "content": chunk_text,
                }
            )

    if not all_chunks:
        logger.info(
            "ingest_session_document: no text content found for session %s", session_id
        )
        return 0

    texts = [c["content"] for c in all_chunks]

    try:
        vectors = _embed(texts)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "ingest_session_document: embedding failed for session %s — %s",
            session_id,
            exc,
        )
        # Store chunks without embeddings so at least keyword search is possible.
        vectors = [None] * len(texts)  # type: ignore[list-item]

    rows: List[SlideChunk] = []
    for chunk_meta, vector in zip(all_chunks, vectors):
        rows.append(
            SlideChunk(
                id=uuid.uuid4(),
                session_id=session_id,
                slide_number=chunk_meta["slide_number"],
                chunk_index=chunk_meta["chunk_index"],
                content=chunk_meta["content"],
                embedding=vector,
            )
        )

    db.add_all(rows)
    db.commit()

    logger.info(
        "ingest_session_document: stored %d chunks for session %s",
        len(rows),
        session_id,
    )
    return len(rows)


def ingest_session_document_background(
    session_id: uuid.UUID,
    slides: List[Dict[str, Any]],
) -> None:
    """
    Background-task wrapper for session slide ingestion.

    Uses a fresh DB session because request-scoped sessions are not safe to
    reuse after the upload response has been sent.
    """
    db = SessionLocal()
    try:
        ingest_session_document(session_id, slides, db)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Background RAG ingestion failed for session %s: %s",
            session_id,
            exc,
        )
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Avatar knowledge-document ingestion
# ---------------------------------------------------------------------------


def ingest_avatar_knowledge_document(
    document_id: uuid.UUID,
    avatar_configuration_id: uuid.UUID,
    file_content: bytes,
    file_name: str,
    db: DBSession,
) -> int:
    """
    Extract text from an avatar knowledge document, chunk, embed, and persist
    as KnowledgeChunk rows.

    Scoping strategy: both course_id and session_id are left NULL; the source
    tag "avatar_knowledge:{avatar_configuration_id}:{document_id}" is the
    stable identifier used to delete stale chunks on re-upload.

    Also writes the extracted plain text back to KnowledgeDocument.content_text
    so it is available for direct inspection without hitting the chunks table.

    Returns the number of chunks stored (0 if no extractable text found).
    """
    source_tag = f"avatar_knowledge:{avatar_configuration_id}:{document_id}"

    # Delete stale chunks from any previous upload of the same document.
    db.query(KnowledgeChunk).filter(
        KnowledgeChunk.source == source_tag,
    ).delete()

    raw_text = _extract_text_from_content(file_content, file_name)

    # Persist extracted text on the document record itself.
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if doc is not None:
        doc.content_text = raw_text or None
        db.flush()

    if not raw_text or not raw_text.strip():
        logger.info(
            "ingest_avatar_knowledge_document: no text extracted from %s (doc %s)",
            file_name,
            document_id,
        )
        db.commit()
        return 0

    return _store_avatar_knowledge_chunks(document_id, avatar_configuration_id, raw_text, db)


def ingest_avatar_knowledge_text(
    document_id: uuid.UUID,
    avatar_configuration_id: uuid.UUID,
    raw_text: str,
    db: DBSession,
) -> int:
    """
    Chunk and embed knowledge that was typed in rather than uploaded as a file
    (KnowledgeDocument.content_text), so voice sessions can retrieve it too.
    Re-running replaces the document's previous chunks.
    """
    source_tag = f"avatar_knowledge:{avatar_configuration_id}:{document_id}"
    db.query(KnowledgeChunk).filter(KnowledgeChunk.source == source_tag).delete()
    if not raw_text or not raw_text.strip():
        db.commit()
        return 0
    return _store_avatar_knowledge_chunks(document_id, avatar_configuration_id, raw_text, db)


def _store_avatar_knowledge_chunks(
    document_id: uuid.UUID,
    avatar_configuration_id: uuid.UUID,
    raw_text: str,
    db: DBSession,
) -> int:
    source_tag = f"avatar_knowledge:{avatar_configuration_id}:{document_id}"
    raw_chunks = _chunk_text(raw_text)
    if not raw_chunks:
        db.commit()
        return 0

    try:
        vectors = _embed(raw_chunks)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "ingest_avatar_knowledge_document: embedding failed for doc %s — %s",
            document_id,
            exc,
        )
        vectors = [None] * len(raw_chunks)  # type: ignore[list-item]

    rows: List[KnowledgeChunk] = [
        KnowledgeChunk(
            id=uuid.uuid4(),
            course_id=None,
            session_id=None,
            source=source_tag,
            content=chunk,
            embedding=vector,
        )
        for chunk, vector in zip(raw_chunks, vectors)
    ]

    db.add_all(rows)
    db.commit()

    logger.info(
        "ingest_avatar_knowledge_document: stored %d chunks for doc %s (avatar_config %s)",
        len(rows),
        document_id,
        avatar_configuration_id,
    )
    return len(rows)


def ingest_avatar_knowledge_text_background(
    document_id: uuid.UUID,
    avatar_configuration_id: uuid.UUID,
    raw_text: str,
) -> None:
    """Background-task wrapper for typed-in avatar knowledge."""
    db = SessionLocal()
    try:
        ingest_avatar_knowledge_text(document_id, avatar_configuration_id, raw_text, db)
    except Exception as exc:  # noqa: BLE001
        logger.error("Background ingestion failed for typed knowledge %s: %s", document_id, exc)
        db.rollback()
    finally:
        db.close()


def ingest_avatar_knowledge_document_background(
    document_id: uuid.UUID,
    avatar_configuration_id: uuid.UUID,
    file_content: bytes,
    file_name: str,
) -> None:
    """Background-task wrapper for avatar knowledge document ingestion."""
    db = SessionLocal()
    try:
        ingest_avatar_knowledge_document(
            document_id, avatar_configuration_id, file_content, file_name, db
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Background RAG ingestion failed for knowledge document %s: %s",
            document_id,
            exc,
        )
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def retrieve_context(
    session_id: uuid.UUID,
    query: str,
    top_k: int = 5,
    db: DBSession = None,  # type: ignore[assignment]
    course_id: Optional[uuid.UUID] = None,
    avatar_configuration_id: Optional[uuid.UUID] = None,
    solution_texts: Optional[List[str]] = None,
    student_texts: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Embed ``query`` and return the ``top_k`` most relevant chunks for the
    given session, ordered by cosine similarity.

    Three sources are searched:
    1. ``SlideChunk`` rows for ``session_id`` — the session's slide content.
    2. ``KnowledgeChunk`` rows for ``course_id`` — uploaded course materials
       (textbooks, articles, etc.).  Only searched when ``course_id`` is provided.
    3. ``KnowledgeChunk`` rows uploaded to the avatar (tag
       ``avatar_knowledge:{avatar_configuration_id}:{document_id}``). Only
       searched when ``avatar_configuration_id`` is provided. Every document
       still on the avatar counts as approved by its owner (ADR 0008); deleted
       documents have no chunks left.

    ``solution_texts`` / ``student_texts``: sessions created before solution
    slides were excluded from indexing still have them as slide chunks. A slide
    chunk found only in a solution slide is dropped, so answers never reach a
    learner.

    Returns a list of dicts::

        [{"slide_number": int|None, "chunk_index": int, "content": str,
          "score": float, "source": "slide"|"course_material"|"avatar_knowledge",
          "document_title": str (avatar_knowledge only)}]

    Falls back to a plain text search (ILIKE) when pgvector is unavailable.
    """
    if not query or not query.strip():
        return []
    results = _retrieve(session_id, query, top_k * 2, db, course_id, avatar_configuration_id)
    if solution_texts:
        results = [
            r for r in results
            if not _is_solution_only(r, solution_texts, student_texts or [])
        ]
    _attach_document_titles(results, db)
    return results[:top_k]


def _avatar_source_prefix(avatar_configuration_id: uuid.UUID) -> str:
    return f"avatar_knowledge:{avatar_configuration_id}:"


def _is_solution_only(chunk: Dict[str, Any], solution_texts: List[str], student_texts: List[str]) -> bool:
    if chunk.get("source") != "slide":
        return False
    content = (chunk.get("content") or "").strip()
    if not content:
        return False
    in_solution = any(content in t for t in solution_texts)
    in_student = any(content in t for t in student_texts)
    return in_solution and not in_student


def _attach_document_titles(results: List[Dict[str, Any]], db: DBSession) -> None:
    """Label avatar-knowledge chunks with their document title for citations."""
    doc_ids = {}
    for r in results:
        tag = r.pop("_tag", None)
        if r.get("source") == "avatar_knowledge" and tag:
            try:
                doc_ids[id(r)] = uuid.UUID(tag.rsplit(":", 1)[1])
            except (ValueError, IndexError):
                continue
    if not doc_ids:
        return
    titles = {
        d.id: d.title
        for d in db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(set(doc_ids.values()))).all()
    }
    for r in results:
        if id(r) in doc_ids:
            r["document_title"] = titles.get(doc_ids[id(r)])


def _retrieve(
    session_id: uuid.UUID,
    query: str,
    top_k: int,
    db: DBSession,
    course_id: Optional[uuid.UUID],
    avatar_configuration_id: Optional[uuid.UUID],
) -> List[Dict[str, Any]]:

    # ── Determine whether any embeddings exist to decide vector vs keyword ──
    slide_sample = (
        db.query(SlideChunk)
        .filter(
            SlideChunk.session_id == session_id,
            SlideChunk.embedding.isnot(None),
        )
        .first()
    )

    knowledge_sample = None
    if course_id is not None:
        knowledge_sample = (
            db.query(KnowledgeChunk)
            .filter(
                KnowledgeChunk.course_id == course_id,
                KnowledgeChunk.embedding.isnot(None),
            )
            .first()
        )

    avatar_sample = None
    if avatar_configuration_id is not None:
        avatar_sample = (
            db.query(KnowledgeChunk)
            .filter(
                KnowledgeChunk.source.like(_avatar_source_prefix(avatar_configuration_id) + "%"),
                KnowledgeChunk.embedding.isnot(None),
            )
            .first()
        )

    use_vector = (
        slide_sample is not None or knowledge_sample is not None or avatar_sample is not None
    )

    if not use_vector:
        return _keyword_fallback(
            session_id, query, top_k, db, course_id=course_id,
            avatar_configuration_id=avatar_configuration_id,
        )

    try:
        query_vector = _embed([query])[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "retrieve_context: embedding failed — %s; using keyword fallback", exc
        )
        return _keyword_fallback(
            session_id, query, top_k, db, course_id=course_id,
            avatar_configuration_id=avatar_configuration_id,
        )

    results: List[Dict[str, Any]] = []

    # ── 1. Slide chunks (session-scoped) ────────────────────────────────────
    if slide_sample is not None:
        slide_rows = db.execute(
            text(
                "SELECT slide_number, chunk_index, content, "
                "1 - (embedding <=> CAST(:vec AS vector)) AS score "
                "FROM slide_chunks "
                "WHERE session_id = :sid AND embedding IS NOT NULL "
                "ORDER BY score DESC "
                "LIMIT :k"
            ),
            {"vec": str(query_vector), "sid": str(session_id), "k": top_k},
        ).fetchall()

        results.extend(
            {
                "slide_number": row.slide_number,
                "chunk_index": row.chunk_index,
                "content": row.content,
                "score": float(row.score),
                "source": "slide",
            }
            for row in slide_rows
        )

    # ── 2. Knowledge chunks (course-scoped) ─────────────────────────────────
    if course_id is not None and knowledge_sample is not None:
        knowledge_rows = db.execute(
            text(
                "SELECT content, source, "
                "1 - (embedding <=> CAST(:vec AS vector)) AS score "
                "FROM knowledge_chunks "
                "WHERE course_id = :cid AND embedding IS NOT NULL "
                "ORDER BY score DESC "
                "LIMIT :k"
            ),
            {"vec": str(query_vector), "cid": str(course_id), "k": top_k},
        ).fetchall()

        results.extend(
            {
                "slide_number": None,
                "chunk_index": 0,
                "content": row.content,
                "score": float(row.score),
                "source": "course_material",
            }
            for row in knowledge_rows
        )

    # ── 3. Avatar knowledge (twin-scoped) ───────────────────────────────────
    if avatar_sample is not None:
        avatar_rows = db.execute(
            text(
                "SELECT content, source, "
                "1 - (embedding <=> CAST(:vec AS vector)) AS score "
                "FROM knowledge_chunks "
                "WHERE source LIKE :prefix AND embedding IS NOT NULL "
                "ORDER BY score DESC "
                "LIMIT :k"
            ),
            {
                "vec": str(query_vector),
                "prefix": _avatar_source_prefix(avatar_configuration_id) + "%",
                "k": top_k,
            },
        ).fetchall()

        results.extend(
            {
                "slide_number": None,
                "chunk_index": 0,
                "content": row.content,
                "score": float(row.score),
                "source": "avatar_knowledge",
                "_tag": row.source,
            }
            for row in avatar_rows
        )

    # ── 4. Chunks that never got an embedding (a failed embedding call) ────
    # Found by keyword so a partly embedded document is never invisible. Their
    # score is capped at 0.5 so strong vector matches still rank first.
    results.extend(
        _keyword_fallback(
            session_id, query, top_k, db, course_id=course_id,
            avatar_configuration_id=avatar_configuration_id,
            unembedded_only=True, score_scale=0.5,
        )
    )

    # ── Merge, sort by score, return top-k ──────────────────────────────────
    results.sort(key=lambda c: c["score"], reverse=True)
    return results[:top_k]


_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "your", "with", "this", "that",
    "what", "when", "where", "which", "who", "why", "how", "can", "could", "should",
    "would", "will", "does", "did", "was", "were", "have", "has", "had", "from",
    "about", "into", "they", "them", "there", "then", "than", "some", "any", "all",
    "its", "our", "out", "too", "very", "just", "also", "please", "tell", "explain",
}


def _query_terms(query: str) -> List[str]:
    """Significant words of the question (Latin or Arabic letters, digits)."""
    words = re.findall(r"[0-9a-z\u0600-\u06ff]{3,}", query.lower())
    terms: List[str] = []
    for w in words:
        if w not in _STOPWORDS and w not in terms:
            terms.append(w)
    return terms[:8] or [query.strip().lower()[:100]]


def _match_fraction(content: str, terms: List[str]) -> float:
    text_lower = (content or "").lower()
    return sum(1 for t in terms if t in text_lower) / len(terms)


def _keyword_fallback(
    session_id: uuid.UUID,
    query: str,
    top_k: int,
    db: DBSession,
    course_id: Optional[uuid.UUID] = None,
    avatar_configuration_id: Optional[uuid.UUID] = None,
    unembedded_only: bool = False,
    score_scale: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Return chunks containing any significant word of ``query`` (ILIKE), the
    chunks matching most words first.

    ``unembedded_only`` restricts the search to chunks that have no embedding,
    so the vector search can include them (one failed embedding call must not
    hide a whole document). ``score_scale`` turns the match fraction into a
    score for merging with vector results; without it the score stays None.
    """
    terms = _query_terms(query)
    pool = max(top_k * 4, 20)
    candidates: List[tuple] = []

    def collect(model, scope_filter, to_result):
        filters = [scope_filter, or_(*[model.content.ilike(f"%{t}%") for t in terms])]
        if unembedded_only:
            filters.append(model.embedding.is_(None))
        for row in db.query(model).filter(*filters).limit(pool).all():
            candidates.append((_match_fraction(row.content, terms), to_result(row)))

    collect(
        SlideChunk,
        SlideChunk.session_id == session_id,
        lambda row: {
            "slide_number": row.slide_number,
            "chunk_index": row.chunk_index,
            "content": row.content,
            "source": "slide",
        },
    )
    if course_id is not None:
        collect(
            KnowledgeChunk,
            KnowledgeChunk.course_id == course_id,
            lambda row: {
                "slide_number": None,
                "chunk_index": 0,
                "content": row.content,
                "source": "course_material",
            },
        )
    if avatar_configuration_id is not None:
        collect(
            KnowledgeChunk,
            KnowledgeChunk.source.like(_avatar_source_prefix(avatar_configuration_id) + "%"),
            lambda row: {
                "slide_number": None,
                "chunk_index": 0,
                "content": row.content,
                "source": "avatar_knowledge",
                "_tag": row.source,
            },
        )

    candidates.sort(key=lambda c: c[0], reverse=True)
    results = []
    for fraction, item in candidates[:top_k]:
        item["score"] = round(fraction * score_scale, 4) if score_scale is not None else None
        results.append(item)
    return results


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def build_grounded_prompt(
    session_id: uuid.UUID,
    query: str,
    persona: Optional[str] = None,
    student_memory: Optional[str] = None,
    db: DBSession = None,  # type: ignore[assignment]
) -> str:
    """
    Retrieve the most relevant chunks for ``query`` and assemble a grounded
    context block for injection into the system prompt.

    Format::

        [Retrieved context — use ONLY this to answer the student's question]
        <source slide=1>
        ...text...
        </source>

    Prepends ``persona`` and ``student_memory`` if provided.
    """
    chunks = retrieve_context(session_id, query, top_k=5, db=db)

    parts: List[str] = []

    if persona:
        parts.append(persona)

    if student_memory:
        parts.append(f"[Student context]\n{student_memory}")

    if chunks:
        source_blocks = "\n".join(
            f'<source slide={c["slide_number"]}>\n{c["content"]}\n</source>'
            for c in chunks
        )
        parts.append(
            "[Retrieved context — answer ONLY from these sources]\n" + source_blocks
        )
    else:
        parts.append(
            "[No relevant slide content found for this query. "
            "If the answer is not in the slides, say so explicitly.]"
        )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Session- and twin-scoped retrieval (voice search and both chats)
# ---------------------------------------------------------------------------


def retrieve_for_twin(
    db: DBSession,
    query: str,
    *,
    session: Any = None,
    avatar_id: Optional[uuid.UUID] = None,
    top_k: int = 8,
) -> List[Dict[str, Any]]:
    """
    Everything indexed for a twin's conversation: the session's slides, its
    course's materials and the avatar's uploaded knowledge. Hidden solution
    slides are never returned. ``session`` is a Session row (or None for a
    conversation outside a session); ``avatar_id`` defaults to the session's.
    """
    from app.database.models import AvatarConfiguration

    avatar_id = avatar_id or (getattr(session, "avatar_id", None) if session else None)
    avatar_config_id = None
    if avatar_id:
        avatar_config_id = (
            db.query(AvatarConfiguration.id)
            .filter(AvatarConfiguration.avatar_id == avatar_id)
            .scalar()
        )

    slides = (getattr(session, "slides_details", None) or []) if session else []
    solution_texts = [
        s.get("content") or "" for s in slides
        if isinstance(s, dict) and s.get("source") == "solution"
    ]
    student_texts = [
        s.get("content") or "" for s in slides
        if isinstance(s, dict) and s.get("source") != "solution"
    ]

    return retrieve_context(
        session.id if session else None,
        query,
        top_k=top_k,
        db=db,
        course_id=getattr(session, "course_id", None) if session else None,
        avatar_configuration_id=avatar_config_id,
        solution_texts=solution_texts,
        student_texts=student_texts,
    )


def _chunk_label(chunk: Dict[str, Any]) -> str:
    if chunk.get("source") == "avatar_knowledge":
        return f"document: {chunk.get('document_title') or 'uploaded document'}"
    if chunk.get("source") == "course_material":
        return "course material"
    if chunk.get("slide_number") is not None:
        return f"slide {chunk['slide_number']}"
    return "session content"


def knowledge_for_chat(
    db: DBSession,
    query: Optional[str],
    *,
    session: Any = None,
    avatar: Any = None,
    top_k: int = 8,
    max_chars_per_unindexed_doc: int = 4000,
) -> List[str]:
    """
    Knowledge passages for a chat prompt: the passages most relevant to the
    current message, each labelled with where it came from.

    Documents that have never been indexed (uploaded before indexing worked)
    are still included as capped text, so nothing the twin used to see is lost.
    With no message yet (an opening turn), only that fallback is used.
    """
    passages: List[str] = []
    if query and query.strip():
        avatar_id = getattr(avatar, "id", None)
        for chunk in retrieve_for_twin(db, query, session=session, avatar_id=avatar_id, top_k=top_k):
            passages.append(f"(from {_chunk_label(chunk)})\n{chunk['content'].strip()}")

    cfg = getattr(avatar, "configuration", None)
    if cfg is not None:
        indexed = {
            row[0].rsplit(":", 1)[-1]
            for row in db.query(KnowledgeChunk.source)
            .filter(KnowledgeChunk.source.like(_avatar_source_prefix(cfg.id) + "%"))
            .distinct()
            .all()
        }
        for doc in cfg.knowledge_documents or []:
            if str(doc.id) in indexed or not (doc.content_text or "").strip():
                continue
            passages.append(
                f"(from document: {doc.title or 'uploaded document'})\n"
                f"{doc.content_text[:max_chars_per_unindexed_doc].strip()}"
            )
    return passages
