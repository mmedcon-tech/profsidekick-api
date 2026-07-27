"""create subscriber_voice_preferences table

Revision ID: v9tts0002
Revises: v9tts0001
Create Date: 2026-07-03 00:00:01.000000

Dual voice pipeline (Pipeline B) — one row per subscriber holding their
optional voice override (provider, voice_id, dialect). Absence of a row
means "use the publisher default."
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v9tts0002"
down_revision = "v9tts0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriber_voice_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("voice_id", sa.String(length=200), nullable=True),
        sa.Column("dialect", sa.String(length=50), nullable=True),
        sa.Column(
            "is_valid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_subscriber_voice_preferences_user_id",
        "subscriber_voice_preferences",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subscriber_voice_preferences_user_id",
        table_name="subscriber_voice_preferences",
    )
    op.drop_table("subscriber_voice_preferences")
