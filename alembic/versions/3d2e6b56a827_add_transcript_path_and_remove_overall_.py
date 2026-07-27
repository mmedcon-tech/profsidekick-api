"""add transcript path and remove overall confidence

Revision ID: 3d2e6b56a827
Revises: 5c40ab01a792
Create Date: 2026-07-12 18:05:46.665000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3d2e6b56a827"
down_revision: Union[str, None] = "5c40ab01a792"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sae_submissions",
        sa.Column(
            "handwritten_transcript_file_path",
            sa.String(length=500),
            nullable=True,
        ),
    )

    op.drop_column(
        "sae_submissions",
        "overall_confidence",
    )


def downgrade() -> None:
    op.add_column(
        "sae_submissions",
        sa.Column(
            "overall_confidence",
            sa.String(length=50),
            nullable=True,
        ),
    )

    op.drop_column(
        "sae_submissions",
        "handwritten_transcript_file_path",
    )