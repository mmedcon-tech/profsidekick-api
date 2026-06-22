"""Wave 3: create avatar_courses join table.

Links avatars to courses for auto-enrollment on subscription (R50, R51).
When a subscriber subscribes to an avatar, they are automatically enrolled
in every course linked via this table.

Revision ID: w8037
Revises: w7036
Create Date: 2026-06-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w8037"
down_revision = "w7036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatar_courses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "avatar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "added_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_avatar_courses_avatar_id", "avatar_courses", ["avatar_id"])
    op.create_index("ix_avatar_courses_course_id", "avatar_courses", ["course_id"])
    op.create_unique_constraint(
        "uq_avatar_courses_avatar_course",
        "avatar_courses",
        ["avatar_id", "course_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_avatar_courses_avatar_course", "avatar_courses", type_="unique"
    )
    op.drop_index("ix_avatar_courses_course_id", table_name="avatar_courses")
    op.drop_index("ix_avatar_courses_avatar_id", table_name="avatar_courses")
    op.drop_table("avatar_courses")
