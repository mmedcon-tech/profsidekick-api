"""add RAG slide_chunks and knowledge_chunks tables

Revision ID: d3333333333d
Revises: c2222222222c
Create Date: 2026-06-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d3333333333d"
down_revision: Union[str, None] = "c2222222222c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    def get_cols(table):
        if table not in existing_tables:
            return []
        return [c['name'] for c in inspector.get_columns(table)]

    def get_fks(table):
        if table not in existing_tables:
            return []
        return [f['name'] for f in inspector.get_foreign_keys(table)]

    def get_indexes(table):
        if table not in existing_tables:
            return []
        return [i['name'] for i in inspector.get_indexes(table)]

    # Enable pgvector extension (idempotent — safe to run multiple times).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "slide_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slide_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # vector(1536) — OpenAI text-embedding-3-small dimensionality
        sa.Column(
            "embedding",
            sa.Text().with_variant(sa.text("vector(1536)"), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_slide_chunks_session_id", "slide_chunks", ["session_id"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # vector(1536) — OpenAI text-embedding-3-small dimensionality
        sa.Column(
            "embedding",
            sa.Text().with_variant(sa.text("vector(1536)"), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_chunks_session_id", "knowledge_chunks", ["session_id"]
    )

    # IVFFlat indexes for approximate nearest-neighbour search.
    # lists=100 is a sensible starting point for up to ~1M rows per table.
    # Re-tune with REINDEX as the dataset grows.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_slide_chunks_embedding "
        "ON slide_chunks USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding "
        "ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_embedding", table_name="knowledge_chunks")
    op.drop_index("ix_slide_chunks_embedding", table_name="slide_chunks")
    op.drop_index("ix_knowledge_chunks_session_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_slide_chunks_session_id", table_name="slide_chunks")
    op.drop_table("slide_chunks")
    # Do NOT drop the vector extension — other tables or projects may depend on it.
