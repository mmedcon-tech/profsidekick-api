"""wave1b: new stub tables for session feedback and auto top-up

Revision ID: t1o2p3q4r5s6
Revises: s0n1o2p3q4r5
Create Date: 2026-06-14 00:00:01.000000

Wave 1B — creates four new tables.  All are net-new; no existing table is
altered.  Safe to apply to a live database without downtime.

Tables created:
  session_feedback         End-of-session subscriber ratings
  transcript_feedback      Per-turn inline feedback
  session_persona_switches Log of subscriber persona switches during a run
  auto_top_up_settings     Per-user automatic credit top-up configuration
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "t1o2p3q4r5s6"
down_revision = "s0n1o2p3q4r5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── session_feedback ──────────────────────────────────────────────────────
    op.create_table(
        "session_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("session_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "avatar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("overall_rating", sa.Integer(), nullable=True),
        sa.Column("clarity_rating", sa.Integer(), nullable=True),
        sa.Column("helpfulness_rating", sa.Integer(), nullable=True),
        sa.Column("engagement_rating", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_session_feedback_user_id", "session_feedback", ["user_id"])
    op.create_unique_constraint("uq_session_feedback_session_run_id", "session_feedback", ["session_run_id"])

    # ── transcript_feedback ───────────────────────────────────────────────────
    op.create_table(
        "transcript_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("session_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(20), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_transcript_feedback_session_run_id", "transcript_feedback", ["session_run_id"])
    op.create_index("ix_transcript_feedback_user_id", "transcript_feedback", ["user_id"])

    # ── session_persona_switches ──────────────────────────────────────────────
    op.create_table(
        "session_persona_switches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("session_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("from_persona", sa.String(100), nullable=True),
        sa.Column("to_persona", sa.String(100), nullable=False),
        sa.Column("switched_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("reason", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_session_persona_switches_session_run_id", "session_persona_switches", ["session_run_id"]
    )
    op.create_index("ix_session_persona_switches_user_id", "session_persona_switches", ["user_id"])

    # ── auto_top_up_settings ──────────────────────────────────────────────────
    op.create_table(
        "auto_top_up_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "threshold_credits",
            sa.Numeric(12, 6),
            nullable=False,
            server_default="10",
        ),
        sa.Column(
            "top_up_amount_credits",
            sa.Numeric(12, 6),
            nullable=False,
            server_default="50",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_unique_constraint("uq_auto_top_up_settings_user_id", "auto_top_up_settings", ["user_id"])


def downgrade() -> None:
    op.drop_table("auto_top_up_settings")
    op.drop_table("session_persona_switches")
    op.drop_table("transcript_feedback")
    op.drop_table("session_feedback")
