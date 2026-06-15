"""wave2b: create program_courses table

Revision ID: w2b021
Revises: w2b020
Create Date: 2026-06-14 00:00:09.000000

Wave 2B step 4 — net-new table; references programs and courses.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w2b021"
down_revision = "w2b020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "program_courses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("programs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_unique_constraint(
        "uq_program_courses_program_course",
        "program_courses",
        ["program_id", "course_id"],
    )
    op.create_index("ix_program_courses_program_id", "program_courses", ["program_id"])


def downgrade() -> None:
    op.drop_index("ix_program_courses_program_id", table_name="program_courses")
    op.drop_constraint("uq_program_courses_program_course", "program_courses", type_="unique")
    op.drop_table("program_courses")
