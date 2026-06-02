"""
RAG (Retrieval-Augmented Generation) service.

Responsibilities:
  1. ``ingest_session_document`` — chunk slide text, embed each chunk with
     OpenAI text-embedding-3-small, and store SlideChunk rows.
  2. ``retrieve_context`` — cosine-similarity search against stored embeddings,
     returning the top-k most relevant text chunks for a given query.
  3. ``build_grounded_prompt`` — assembles the final context block that is
     injected into the OpenAI Realtime / Chat Completions system prompt.

Embedding model: text-embedding-3-small (1536 dimensions, $0.02 / 1M tokens).
Chunking strategy: ~400-token windows with 50-token overlap (character-based
approximation: 1 token ≈ 4 characters → ~1 600 chars per chunk, 200-char overlap).
"""
from __future__ import annotations

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
# Ingestion
# ---------------------------------------------------------------------------


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
) -> List[Dict[str, Any]]:
    """
    Embed ``query`` and return the ``top_k`` most relevant ``SlideChunk``
    rows for the given ``session_id``, ordered by cosine similarity.

    Returns a list of dicts:
      ``[{"slide_number": int, "chunk_index": int, "content": str, "score": float}]``

    Falls back to a plain text search (ILIKE) when pgvector is unavailable.
    """
    if not query or not query.strip():
        return []

    # Check whether any embeddings exist for this session.
    sample = (
        db.query(SlideChunk)
        .filter(
            SlideChunk.session_id == session_id,
            SlideChunk.embedding.isnot(None),
        )
        .first()
    )

    if sample is None:
        # No embeddings — fall back to keyword search.
        return _keyword_fallback(session_id, query, top_k, db)

    try:
        query_vector = _embed([query])[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("retrieve_context: embedding failed — %s; using keyword fallback", exc)
        return _keyword_fallback(session_id, query, top_k, db)

    # pgvector cosine distance operator: <=>
    # 1 - cosine_distance = cosine_similarity
    results = db.execute(
        text(
            "SELECT id, slide_number, chunk_index, content, "
            "1 - (embedding <=> CAST(:vec AS vector)) AS score "
            "FROM slide_chunks "
            "WHERE session_id = :sid "
            "ORDER BY score DESC "
            "LIMIT :k"
        ),
        {
            "vec": str(query_vector),
            "sid": str(session_id),
            "k": top_k,
        },
    ).fetchall()

    return [
        {
            "slide_number": row.slide_number,
            "chunk_index": row.chunk_index,
            "content": row.content,
            "score": float(row.score),
        }
        for row in results
    ]


def _keyword_fallback(
    session_id: uuid.UUID,
    query: str,
    top_k: int,
    db: DBSession,
) -> List[Dict[str, Any]]:
    """Return chunks whose content contains any word from ``query`` (ILIKE)."""
    keyword = f"%{query.strip()[:100]}%"
    rows = (
        db.query(SlideChunk)
        .filter(
            SlideChunk.session_id == session_id,
            SlideChunk.content.ilike(keyword),
        )
        .limit(top_k)
        .all()
    )
    return [
        {
            "slide_number": row.slide_number,
            "chunk_index": row.chunk_index,
            "content": row.content,
            "score": None,
        }
        for row in rows
    ]


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
