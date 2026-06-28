"""wave6: create subscriber_course_progress table

Revision ID: w6027
Revises: w3026
Create Date: 2026-06-15 00:00:00.000000

Wave 6 step 1 — per-subscriber per-course progress tracking (R82).
Unique on (user_id, course_id); session_run_id records the most recent contributing run.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w6027"
down_revision = "w3026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriber_course_progress",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("session_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("completion_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("time_spent_sec", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_session_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_scp_user_id", "subscriber_course_progress", ["user_id"])
    op.create_index("ix_scp_course_id", "subscriber_course_progress", ["course_id"])
    op.create_unique_constraint(
        "uq_subscriber_course_progress",
        "subscriber_course_progress",
        ["user_id", "course_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_subscriber_course_progress", "subscriber_course_progress", type_="unique")
    op.drop_index("ix_scp_course_id", table_name="subscriber_course_progress")
    op.drop_index("ix_scp_user_id", table_name="subscriber_course_progress")
    op.drop_table("subscriber_course_progress")
