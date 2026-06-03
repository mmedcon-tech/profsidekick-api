"""
Tests for the RAG data models (SlideChunk, KnowledgeChunk).

Requires PostgreSQL + pgvector.  Start the test DB before running:
  docker compose -f docker-compose.test.yml up -d
  export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/profsidekick_test
"""

import uuid

import pytest
from sqlalchemy import text

from app.database.models import KnowledgeChunk, SlideChunk
from tests.conftest import engine


def _make_session_id(db_session) -> uuid.UUID:
    """Return the UUID of a minimal Session row (created inline)."""
    from app.database.models import Course, Session, User

    uid = uuid.uuid4()
    user = User(
        id=uid,
        username=f"u_{uid.hex[:8]}",
        email=f"{uid.hex[:8]}@example.com",
        password_hash="x",
        first_name="A",
        last_name="B",
        role="teacher",
    )
    db_session.add(user)

    course = Course(
        id=uuid.uuid4(),
        course_id=f"crs_{uuid.uuid4().hex[:8]}",
        user_id=uid,
        name="Test Course",
    )
    db_session.add(course)

    session = Session(
        id=uuid.uuid4(),
        session_id=f"sess_{uuid.uuid4().hex[:8]}",
        user_id=uid,
        course_id=course.id,
    )
    db_session.add(session)
    db_session.flush()
    return session.id


# ---------------------------------------------------------------------------
# Schema tests — no DB connection required
# ---------------------------------------------------------------------------


class TestSlideChunkModel:
    def test_table_name(self):
        assert SlideChunk.__tablename__ == "slide_chunks"

    def test_required_columns_exist(self):
        cols = {c.name for c in SlideChunk.__table__.columns}
        assert {
            "id",
            "session_id",
            "slide_number",
            "chunk_index",
            "content",
            "embedding",
            "created_at",
        } <= cols

    def test_session_relationship_declared(self):
        assert "session" in SlideChunk.__mapper__.relationships.keys()


class TestKnowledgeChunkModel:
    def test_table_name(self):
        assert KnowledgeChunk.__tablename__ == "knowledge_chunks"

    def test_required_columns_exist(self):
        cols = {c.name for c in KnowledgeChunk.__table__.columns}
        assert {
            "id",
            "session_id",
            "source",
            "content",
            "embedding",
            "created_at",
        } <= cols

    def test_session_relationship_declared(self):
        assert "session" in KnowledgeChunk.__mapper__.relationships.keys()


# ---------------------------------------------------------------------------
# Integration tests — require live DB
# ---------------------------------------------------------------------------


class TestSlideChunkCRUD:
    def test_insert_and_retrieve_slide_chunk(self, db_session):
        session_id = _make_session_id(db_session)

        chunk = SlideChunk(
            id=uuid.uuid4(),
            session_id=session_id,
            slide_number=1,
            chunk_index=0,
            content="Introduction to machine learning concepts.",
        )
        db_session.add(chunk)
        db_session.flush()

        fetched = db_session.query(SlideChunk).filter_by(session_id=session_id).first()
        assert fetched is not None
        assert fetched.content == "Introduction to machine learning concepts."
        assert fetched.slide_number == 1
        assert fetched.chunk_index == 0

    def test_multiple_chunks_per_slide(self, db_session):
        session_id = _make_session_id(db_session)

        for i in range(3):
            db_session.add(
                SlideChunk(
                    id=uuid.uuid4(),
                    session_id=session_id,
                    slide_number=2,
                    chunk_index=i,
                    content=f"Chunk {i} of slide 2.",
                )
            )
        db_session.flush()

        chunks = (
            db_session.query(SlideChunk)
            .filter_by(session_id=session_id, slide_number=2)
            .order_by(SlideChunk.chunk_index)
            .all()
        )
        assert len(chunks) == 3
        assert [c.chunk_index for c in chunks] == [0, 1, 2]


class TestKnowledgeChunkCRUD:
    def test_insert_and_retrieve_knowledge_chunk(self, db_session):
        session_id = _make_session_id(db_session)

        chunk = KnowledgeChunk(
            id=uuid.uuid4(),
            session_id=session_id,
            source="professor_answer",
            content="The gradient descent algorithm minimises loss.",
        )
        db_session.add(chunk)
        db_session.flush()

        fetched = (
            db_session.query(KnowledgeChunk).filter_by(session_id=session_id).first()
        )
        assert fetched is not None
        assert fetched.source == "professor_answer"
        assert "gradient descent" in fetched.content

    def test_valid_source_values(self, db_session):
        session_id = _make_session_id(db_session)

        for source in ("professor_answer", "slide", "post_session_note"):
            db_session.add(
                KnowledgeChunk(
                    id=uuid.uuid4(),
                    session_id=session_id,
                    source=source,
                    content=f"Content from {source}.",
                )
            )
        db_session.flush()

        fetched = (
            db_session.query(KnowledgeChunk).filter_by(session_id=session_id).all()
        )
        assert len(fetched) == 3


# ---------------------------------------------------------------------------
# pgvector-specific tests
# ---------------------------------------------------------------------------


class TestPgVectorColumns:
    def test_slide_chunks_table_has_vector_column(self):
        """The embedding column must be of type vector(1536) in PostgreSQL."""
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT data_type, udt_name "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'slide_chunks' AND column_name = 'embedding'"
                )
            ).fetchone()
        assert result is not None
        # pgvector columns report as USER-DEFINED udt_name = 'vector'
        assert result[1] == "vector"

    def test_knowledge_chunks_table_has_vector_column(self):
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT data_type, udt_name "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'knowledge_chunks' AND column_name = 'embedding'"
                )
            ).fetchone()
        assert result is not None
        assert result[1] == "vector"

    def test_ivfflat_index_exists_on_slide_chunks(self):
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'slide_chunks' "
                    "AND indexname = 'ix_slide_chunks_embedding'"
                )
            ).fetchone()
        assert result is not None, "IVFFlat index on slide_chunks.embedding not found"
