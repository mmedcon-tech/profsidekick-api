"""add sae question comments

Revision ID: 1ed3632f87e8
Revises: 3d2e6b56a827
Create Date: 2026-07-13 10:55:50.084598
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "1ed3632f87e8"
down_revision: Union[str, None] = "3d2e6b56a827"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sae_question_comments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "submission_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "comment",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["sae_submissions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "submission_id",
            "question_id",
            name="uq_sae_comment_submission_question",
        ),
    )

    op.create_index(
        "ix_sae_question_comments_question_id",
        "sae_question_comments",
        ["question_id"],
        unique=False,
    )

    op.create_index(
        "ix_sae_question_comments_submission_id",
        "sae_question_comments",
        ["submission_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sae_question_comments_submission_id",
        table_name="sae_question_comments",
    )

    op.drop_index(
        "ix_sae_question_comments_question_id",
        table_name="sae_question_comments",
    )

    op.drop_table("sae_question_comments")