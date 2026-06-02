"""
Tests for app.services.rag_service.

Requires PostgreSQL + pgvector.  Start the test DB before running:
  docker compose -f docker-compose.test.yml up -d
  export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/profsidekick_test
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _chunk_text — pure function tests (no DB)
# ---------------------------------------------------------------------------

from app.services.rag_service import (  # noqa: E402  (import after path setup)
    _CHARS_OVERLAP,
    _CHARS_PER_CHUNK,
    _chunk_text,
    build_grounded_prompt,
    ingest_session_document,
    retrieve_context,
)


class TestChunkText:
    def test_empty_string_returns_empty_list(self):
        assert _chunk_text("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert _chunk_text("   \n\t  ") == []

    def test_short_content_produces_single_chunk(self):
        content = "Hello world"
        chunks = _chunk_text(content)
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_long_content_produces_multiple_chunks(self):
        # Generate text that is 3× the chunk size to guarantee ≥ 3 chunks
        content = "a " * (_CHARS_PER_CHUNK * 3 // 2)
        chunks = _chunk_text(content)
        assert len(chunks) >= 2

    def test_chunk_length_does_not_exceed_limit(self):
        content = "b " * (_CHARS_PER_CHUNK * 5)
        for chunk in _chunk_text(content):
            assert len(chunk) <= _CHARS_PER_CHUNK

    def test_overlap_between_consecutive_chunks(self):
        # Create content large enough to produce at least 2 chunks.
        # Use unique 10-char tokens so we can verify overlap.
        token = "ABCDEFGHIJ"
        # Each token is 10 chars. We need slightly more than CHARS_PER_CHUNK chars.
        n_tokens = (_CHARS_PER_CHUNK // len(token)) + 20
        content = " ".join([f"{token}{i:04d}" for i in range(n_tokens)])
        chunks = _chunk_text(content)
        assert len(chunks) >= 2, "Need at least 2 chunks to test overlap"

        # Verify that the start of chunk[1] appears near the end of chunk[0].
        first_unique_words_of_chunk1 = chunks[1][:50]
        assert first_unique_words_of_chunk1 in chunks[0], (
            "Expected overlap: start of chunk[1] should appear in chunk[0]"
        )

    def test_none_like_empty_string_handled(self):
        # Callers may pass an empty-string slide; should not raise.
        assert _chunk_text("") == []


# ---------------------------------------------------------------------------
# ingest_session_document — integration tests (require DB)
# ---------------------------------------------------------------------------


@pytest.fixture()
def slides_with_content():
    """Minimal slide list mimicking what file_processor produces."""
    return [
        {
            "slideNumber": 1,
            "content": "Introduction to Machine Learning. " * 50,
        },
        {
            "slideNumber": 2,
            "content": "Supervised learning uses labelled data. " * 50,
        },
        {
            "slideNumber": 3,
            "content": "",  # empty — should produce no chunks
        },
    ]


@pytest.mark.usefixtures("create_tables")
class TestIngestSessionDocument:
    """Integration tests — require real PostgreSQL+pgvector (docker-compose.test.yml)."""

    def test_stores_chunks_for_non_empty_slides(
        self, db_session, test_session, slides_with_content
    ):
        """Chunks should be persisted for slides with content."""
        session_id = test_session.id

        def fake_embed(texts):
            return [[float(i % 100)] * 1536 for i in range(len(texts))]

        with patch("app.services.rag_service._embed", side_effect=fake_embed):
            from app.database.models import SlideChunk

            count = ingest_session_document(session_id, slides_with_content, db_session)

            assert count > 0
            stored = (
                db_session.query(SlideChunk)
                .filter(SlideChunk.session_id == session_id)
                .all()
            )
            assert len(stored) == count

    def test_skips_empty_slides(self, db_session, test_session):
        session_id = test_session.id
        slides = [
            {"slideNumber": 1, "content": ""},
            {"slideNumber": 2, "content": "   "},
        ]
        with patch("app.services.rag_service._embed", return_value=[]):
            count = ingest_session_document(session_id, slides, db_session)
        assert count == 0

    def test_clears_stale_chunks_on_reingest(
        self, db_session, test_session, slides_with_content
    ):
        """Re-uploading the same session should replace, not append, chunks."""
        session_id = test_session.id

        def fake_embed(texts):
            return [[0.1] * 1536 for _ in texts]

        with patch("app.services.rag_service._embed", side_effect=fake_embed):
            from app.database.models import SlideChunk

            ingest_session_document(session_id, slides_with_content, db_session)
            count_after_first = (
                db_session.query(SlideChunk)
                .filter(SlideChunk.session_id == session_id)
                .count()
            )

            ingest_session_document(session_id, slides_with_content, db_session)
            count_after_second = (
                db_session.query(SlideChunk)
                .filter(SlideChunk.session_id == session_id)
                .count()
            )

        assert count_after_second == count_after_first, (
            "Re-ingestion should replace, not duplicate, chunks"
        )

    def test_non_fatal_on_embedding_failure(
        self, db_session, test_session, slides_with_content
    ):
        """If the embedding call throws, chunks should still be stored without embeddings."""
        session_id = test_session.id
        with patch(
            "app.services.rag_service._embed",
            side_effect=RuntimeError("API down"),
        ):
            from app.database.models import SlideChunk

            count = ingest_session_document(session_id, slides_with_content, db_session)
            assert count > 0

            rows = (
                db_session.query(SlideChunk)
                .filter(SlideChunk.session_id == session_id)
                .all()
            )
            # All embeddings should be None (failed gracefully).
            assert all(r.embedding is None for r in rows)


# ---------------------------------------------------------------------------
# retrieve_context — unit tests (mock DB)
# ---------------------------------------------------------------------------


class TestRetrieveContext:
    def test_empty_query_returns_empty_list(self):
        db = MagicMock()
        result = retrieve_context(uuid.uuid4(), "", db=db)
        assert result == []

    def test_whitespace_query_returns_empty_list(self):
        db = MagicMock()
        result = retrieve_context(uuid.uuid4(), "   ", db=db)
        assert result == []

    def test_keyword_fallback_when_no_embeddings(self):
        """When no embedded chunks exist, should fall back to keyword search."""
        db = MagicMock()
        # Simulate: no chunks with embeddings (first() → None).
        db.query.return_value.filter.return_value.first.return_value = None

        # Keyword fallback query returns one matching row.
        fake_row = MagicMock()
        fake_row.slide_number = 1
        fake_row.chunk_index = 0
        fake_row.content = "Machine learning basics"

        db.query.return_value.filter.return_value.limit.return_value.all.return_value = [
            fake_row
        ]

        with patch("app.services.rag_service._embed") as mock_embed:
            results = retrieve_context(
                uuid.uuid4(), "machine learning", top_k=5, db=db
            )
            # _embed should NOT have been called (fallback path).
            mock_embed.assert_not_called()

        assert len(results) == 1
        assert results[0]["slide_number"] == 1
        assert results[0]["score"] is None


# ---------------------------------------------------------------------------
# build_grounded_prompt — unit tests (mock retrieve_context)
# ---------------------------------------------------------------------------


class TestBuildGroundedPrompt:
    def _mock_db(self):
        return MagicMock()

    def test_includes_source_blocks_when_chunks_found(self):
        fake_chunks = [
            {"slide_number": 2, "chunk_index": 0, "content": "Neural networks overview", "score": 0.9},
        ]
        with patch("app.services.rag_service.retrieve_context", return_value=fake_chunks):
            prompt = build_grounded_prompt(
                uuid.uuid4(), "neural networks", db=self._mock_db()
            )
        assert "<source slide=2>" in prompt
        assert "Neural networks overview" in prompt
        assert "Retrieved context" in prompt

    def test_no_sources_message_when_no_chunks(self):
        with patch("app.services.rag_service.retrieve_context", return_value=[]):
            prompt = build_grounded_prompt(
                uuid.uuid4(), "quantum computing", db=self._mock_db()
            )
        assert "No relevant slide content found" in prompt

    def test_prepends_persona_when_provided(self):
        with patch("app.services.rag_service.retrieve_context", return_value=[]):
            prompt = build_grounded_prompt(
                uuid.uuid4(),
                "test query",
                persona="You are a helpful tutor.",
                db=self._mock_db(),
            )
        assert prompt.startswith("You are a helpful tutor.")

    def test_includes_student_memory_when_provided(self):
        with patch("app.services.rag_service.retrieve_context", return_value=[]):
            prompt = build_grounded_prompt(
                uuid.uuid4(),
                "test query",
                student_memory="Student is a beginner.",
                db=self._mock_db(),
            )
        assert "Student context" in prompt
        assert "Student is a beginner." in prompt
