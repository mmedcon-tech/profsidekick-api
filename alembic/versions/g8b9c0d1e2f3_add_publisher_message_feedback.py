"""add publisher_message_feedback table

Revision ID: g8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-06-01

Changes:
  NEW TABLE publisher_message_feedback:
    Per-message thumbs-up/down + optional comment from publishers.
    Used to inject publisher preferences into future system prompts.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "g8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publisher_message_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("publisher_messages.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("publisher_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("avatar_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("avatars.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("rating", sa.String(20), nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("publisher_message_feedback")
