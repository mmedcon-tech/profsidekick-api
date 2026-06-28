"""add students table

Revision ID: u2q3r4s5t6u7
Revises: t1p2q3r4s5t6
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "u2q3r4s5t6u7"
down_revision: Union[str, None] = "t1p2q3r4s5t6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS student_code_seq START 1")

    op.create_table(
        "students",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("student_code", sa.String(20), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    op.create_index("idx_students_code", "students", ["student_code"])
    op.create_index("idx_students_created_by", "students", ["created_by"])


def downgrade() -> None:
    op.drop_index("idx_students_created_by", table_name="students")
    op.drop_index("idx_students_code", table_name="students")
    op.drop_table("students")
    op.execute("DROP SEQUENCE student_code_seq")
