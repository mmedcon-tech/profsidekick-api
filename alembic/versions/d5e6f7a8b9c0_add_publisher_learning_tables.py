"""add publisher learning system tables

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-05-29

Creates:
  publisher_conversations  — chat conversation container
  publisher_messages       — individual chat turns
  feedback_preferences     — preferred / rejected AI response pairs
  publisher_preferences    — per-publisher key-value settings
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
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

    # ── publisher_conversations ──────────────────────────────────────
    op.create_table(
        "publisher_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("publisher_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("avatar_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_publisher_conversations_publisher_id",
                    "publisher_conversations", ["publisher_id"])

    # ── publisher_messages ───────────────────────────────────────────
    op.create_table(
        "publisher_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("publisher_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_publisher_messages_conversation_id",
                    "publisher_messages", ["conversation_id"])

    # ── feedback_preferences ─────────────────────────────────────────
    op.create_table(
        "feedback_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("publisher_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("avatar_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("selected_response", sa.Text, nullable=False),
        sa.Column("rejected_responses", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("feedback_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_feedback_preferences_publisher_id",
                    "feedback_preferences", ["publisher_id"])

    # ── publisher_preferences ────────────────────────────────────────
    op.create_table(
        "publisher_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("publisher_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("publisher_id", "key", name="uq_publisher_preference"),
    )
    op.create_index("ix_publisher_preferences_publisher_id",
                    "publisher_preferences", ["publisher_id"])


def downgrade() -> None:
    op.drop_table("publisher_preferences")
    op.drop_table("feedback_preferences")
    op.drop_table("publisher_messages")
    op.drop_table("publisher_conversations")
