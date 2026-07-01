"""Add sae_assessments table

Creates the assessment container that groups SAE students under a single
exam/test run owned by a publisher. Previously students belonged directly
to a publisher with no cohort grouping; this table is the missing piece.

Note: rubric_id is stored as a plain UUID column with no FK constraint
because the rubrics table does not yet exist in this migration chain.
The FK can be added in a later migration once that table is created.

Revision ID: aa1bb2cc3dd4
Revises: z2b3c4d5e6f7
Create Date: 2026-07-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "aa1bb2cc3dd4"
down_revision: Union[str, None] = "z2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sae_assessments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "publisher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Plain UUID — no FK yet; rubrics table does not exist in this chain.
        sa.Column("rubric_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_sae_assessments_publisher_id", "sae_assessments", ["publisher_id"])
    op.create_index("ix_sae_assessments_course_id", "sae_assessments", ["course_id"])


def downgrade() -> None:
    op.drop_index("ix_sae_assessments_course_id", table_name="sae_assessments")
    op.drop_index("ix_sae_assessments_publisher_id", table_name="sae_assessments")
    op.drop_table("sae_assessments")
