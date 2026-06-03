"""Remove unimplemented RAG infrastructure

Revision ID: m4h5i6j7k8l9
Revises: l3g4h5i6j7k8
Create Date: 2026-06-02

Changes:
  DROP TABLE  knowledge_document_chunks
    — chunk rows were never created (no upload handler populated them).
    — retrieval code path is removed from publisher_chat_service.
    — knowledge content is now always sourced from knowledge_documents.content_text.

  DROP COLUMN user_memories.embedding
    — embedding was never computed or written (always NULL).
    — memory retrieval uses importance + recency ordering, not cosine similarity.

Knowledge document uploads and prompt injection are NOT affected:
  knowledge_documents.content_text remains and is injected as before.
"""

from alembic import op
import sqlalchemy as sa

revision = "m4h5i6j7k8l9"
down_revision = "l3g4h5i6j7k8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the chunks table first (FK references knowledge_documents.id).
    op.drop_table("knowledge_document_chunks")

    # Drop the embedding column from user_memories.
    op.drop_column("user_memories", "embedding")


def downgrade() -> None:
    # Restore embedding column (nullable — no data recovery possible).
    op.add_column(
        "user_memories",
        sa.Column("embedding", sa.Text, nullable=True),
    )

    # Recreate the chunks table (empty — no data recovery possible).
    op.create_table(
        "knowledge_document_chunks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "knowledge_document_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_knowledge_document_chunks_knowledge_document_id",
        "knowledge_document_chunks",
        ["knowledge_document_id"],
    )
