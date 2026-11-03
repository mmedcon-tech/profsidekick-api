"""Clinic Knowledge Hub: effective dates on content, embedding model on chunks.

Revision ID: d4e5f6a7b8c9
Revises: c3e4f5a6b7d8
"""
import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3e4f5a6b7d8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("care_content_items", sa.Column("effective_from", sa.DateTime(), nullable=True))
    op.add_column("care_content_items", sa.Column("effective_to", sa.DateTime(), nullable=True))
    op.add_column("care_content_chunks", sa.Column("embedding_model", sa.String(120), nullable=True))
    # every existing vector was produced by the only model used so far
    op.execute("UPDATE care_content_chunks SET embedding_model = 'openai:text-embedding-3-small' WHERE embedding IS NOT NULL")


def downgrade():
    op.drop_column("care_content_chunks", "embedding_model")
    op.drop_column("care_content_items", "effective_to")
    op.drop_column("care_content_items", "effective_from")
