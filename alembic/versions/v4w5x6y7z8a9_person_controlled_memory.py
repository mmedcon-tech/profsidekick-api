"""Evidence-backed memory, per-twin consent and durable extraction jobs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "v4w5x6y7z8a9"
down_revision = "u3v4w5x6y7z8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = [
        sa.Column("kind", sa.String(30), nullable=False, server_default="note"),
        sa.Column("topic", sa.String(200)),
        sa.Column("evidence_quote", sa.Text()),
        sa.Column("confidence", sa.Float()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "visibility", pg.JSONB(), nullable=False, server_default='["learner"]'
        ),
        sa.Column("consent_basis", sa.String(40)),
        sa.Column(
            "source_run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("session_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("times_seen", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_confirmed_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("memory_key", sa.String(64)),
    ]
    for column in columns:
        op.add_column("user_memories", column)
    op.create_index("ix_user_memories_expires_at", "user_memories", ["expires_at"])
    op.execute(
        "UPDATE user_memories SET expires_at = COALESCE(updated_at, created_at, NOW()) + INTERVAL '12 months'"
    )
    op.create_table(
        "memory_controls",
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "twin_memory_consents",
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "avatar_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("consented_at", sa.DateTime()),
        sa.Column(
            "education_shared", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("reset_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "memory_suppressions",
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "avatar_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("memory_key", sa.String(64), primary_key=True),
    )
    op.create_table(
        "memory_jobs",
        sa.Column(
            "run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("session_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "memory_jobs",
        "memory_suppressions",
        "twin_memory_consents",
        "memory_controls",
    ):
        op.drop_table(table)
    op.drop_index("ix_user_memories_expires_at", table_name="user_memories")
    for name in (
        "kind",
        "topic",
        "evidence_quote",
        "confidence",
        "status",
        "visibility",
        "consent_basis",
        "source_run_id",
        "times_seen",
        "last_confirmed_at",
        "expires_at",
        "memory_key",
    ):
        op.drop_column("user_memories", name)
