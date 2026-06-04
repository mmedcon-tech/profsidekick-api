"""add rag_status, rag_error, rag_chunks to course_materials

Revision ID: f5555555555f
Revises: e4444444444e
Create Date: 2026-06-04 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5555555555f"
down_revision: Union[str, None] = "e4444444444e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "course_materials",
        sa.Column("rag_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "course_materials",
        sa.Column("rag_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "course_materials",
        sa.Column("rag_chunks", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("course_materials", "rag_chunks")
    op.drop_column("course_materials", "rag_error")
    op.drop_column("course_materials", "rag_status")
