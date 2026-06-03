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
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.database.models import KnowledgeChunk, SlideChunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chunking constants
# ---------------------------------------------------------------------------

_CHARS_PER_CHUNK = 1_600   # ≈ 400 tokens at 4 chars/token
_CHARS_OVERLAP = 200       # ≈ 50 tokens of overlap between consecutive chunks

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


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def retrieve_context(
    session_id: uuid.UUID,
    query: str,
    top_k: int = 5,
    db: DBSession = None,  # type: ignore[assignment]
    course_id: Optional[uuid.UUID] = None,
) -> List[Dict[str, Any]]:
    """
    Embed ``query`` and return the ``top_k`` most relevant chunks for the
    given session, ordered by cosine similarity.

    Two sources are searched:
    1. ``SlideChunk`` rows for ``session_id`` — the session's slide content.
    2. ``KnowledgeChunk`` rows for ``course_id`` — uploaded course materials
       (textbooks, articles, etc.).  Only searched when ``course_id`` is provided.

    Returns a list of dicts::

        [{"slide_number": int|None, "chunk_index": int, "content": str,
          "score": float, "source": "slide"|"course_material"}]
    """

    Falls back to a plain text search (ILIKE) when pgvector is unavailable.
    """
    if not query or not query.strip():
        return []

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

    use_vector = slide_sample is not None or knowledge_sample is not None

    if not use_vector:
        return _keyword_fallback(session_id, query, top_k, db, course_id=course_id)

    try:
        query_vector = _embed([query])[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("retrieve_context: embedding failed — %s; using keyword fallback", exc)
        return _keyword_fallback(session_id, query, top_k, db, course_id=course_id)

    results: List[Dict[str, Any]] = []

    # ── 1. Slide chunks (session-scoped) ────────────────────────────────────
    if slide_sample is not None:
        slide_rows = db.execute(
            text(
                "SELECT slide_number, chunk_index, content, "
                "1 - (embedding <=> CAST(:vec AS vector)) AS score "
                "FROM slide_chunks "
                "WHERE session_id = :sid "
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
                "SELECT chunk_index, content, source, "
                "1 - (embedding <=> CAST(:vec AS vector)) AS score "
                "FROM knowledge_chunks "
                "WHERE course_id = :cid "
                "ORDER BY score DESC "
                "LIMIT :k"
            ),
            {"vec": str(query_vector), "cid": str(course_id), "k": top_k},
        ).fetchall()

        results.extend(
            {
                "slide_number": None,
                "chunk_index": row.chunk_index if hasattr(row, "chunk_index") else 0,
                "content": row.content,
                "score": float(row.score),
                "source": "course_material",
            }
            for row in knowledge_rows
        )

    # ── Merge, sort by score, return top-k ──────────────────────────────────
    results.sort(key=lambda c: c["score"], reverse=True)
    return results[:top_k]


def _keyword_fallback(
    session_id: uuid.UUID,
    query: str,
    top_k: int,
    db: DBSession,
    course_id: Optional[uuid.UUID] = None,
) -> List[Dict[str, Any]]:
    """Return chunks whose content contains any word from ``query`` (ILIKE)."""
    keyword = f"%{query.strip()[:100]}%"
    results: List[Dict[str, Any]] = []

    slide_rows = (
        db.query(SlideChunk)
        .filter(
            SlideChunk.session_id == session_id,
            SlideChunk.content.ilike(keyword),
        )
        .limit(top_k)
        .all()
    )
    results.extend(
        {
            "slide_number": row.slide_number,
            "chunk_index": row.chunk_index,
            "content": row.content,
            "score": None,
            "source": "slide",
        }
        for row in slide_rows
    )

    if course_id is not None:
        knowledge_rows = (
            db.query(KnowledgeChunk)
            .filter(
                KnowledgeChunk.course_id == course_id,
                KnowledgeChunk.content.ilike(keyword),
            )
            .limit(top_k)
            .all()
        )
        results.extend(
            {
                "slide_number": None,
                "chunk_index": 0,
                "content": row.content,
                "score": None,
                "source": "course_material",
            }
            for row in knowledge_rows
        )

    return results[:top_k]



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
