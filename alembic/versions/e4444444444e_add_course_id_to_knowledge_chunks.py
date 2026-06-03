"""add course_id to knowledge_chunks and make session_id nullable

Revision ID: e4444444444e
Revises: d3333333333d
Create Date: 2026-06-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e4444444444e"
down_revision: Union[str, None] = "d3333333333d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make session_id nullable — course-material chunks are course-scoped,
    # not session-scoped.
    op.alter_column(
        "knowledge_chunks",
        "session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    # Widen source column to accommodate "course_material:<uuid>" values.
    op.alter_column(
        "knowledge_chunks",
        "source",
        existing_type=sa.String(length=50),
        type_=sa.String(length=100),
        existing_nullable=False,
    )

    # Add course_id FK — nullable, set for course-material chunks.
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_knowledge_chunks_course_id",
        "knowledge_chunks",
        "courses",
        ["course_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_knowledge_chunks_course_id",
        "knowledge_chunks",
        ["course_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_course_id", table_name="knowledge_chunks")
    op.drop_constraint(
        "fk_knowledge_chunks_course_id",
        "knowledge_chunks",
        type_="foreignkey",
    )
    op.drop_column("knowledge_chunks", "course_id")

    op.alter_column(
        "knowledge_chunks",
        "source",
        existing_type=sa.String(length=100),
        type_=sa.String(length=50),
        existing_nullable=False,
    )

    op.alter_column(
        "knowledge_chunks",
        "session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
