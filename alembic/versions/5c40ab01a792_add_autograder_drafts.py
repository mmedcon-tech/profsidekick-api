"""add autograder drafts

Revision ID: 5c40ab01a792
Revises: 20f2092b2fc8
Create Date: 2026-07-06 02:24:12.326525

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "5c40ab01a792"
down_revision: Union[str, None] = "20f2092b2fc8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "autograder_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("handwritten_filename", sa.String(length=255), nullable=True),
        sa.Column("handwritten_file_path", sa.String(length=500), nullable=False),
        sa.Column("webassign_filename", sa.String(length=255), nullable=True),
        sa.Column("webassign_file_path", sa.String(length=500), nullable=False),
        sa.Column("transcript_text", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("transcript_model", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_autograder_drafts_created_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_autograder_drafts_student_id",
            ondelete="RESTRICT",
        ),
    )

    op.create_index(
        "idx_autograder_drafts_student_id",
        "autograder_drafts",
        ["student_id"],
    )

    op.create_index(
        "idx_autograder_drafts_created_at",
        "autograder_drafts",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_autograder_drafts_created_at", table_name="autograder_drafts")
    op.drop_index("idx_autograder_drafts_student_id", table_name="autograder_drafts")
    op.drop_table("autograder_drafts")