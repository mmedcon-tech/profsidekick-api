"""add rag_status, rag_error, rag_chunks to course_materials

Revision ID: f5555555555f
Revises: 736a240d08c6
Create Date: 2026-06-04 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5555555555f"
down_revision: Union[str, None] = "736a240d08c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    def get_cols(table):
        if table not in existing_tables:
            return []
        return [c['name'] for c in inspector.get_columns(table)]

    def get_fks(table):
        if table not in existing_tables:
            return []
        return [f['name'] for f in inspector.get_foreign_keys(table)]

    def get_indexes(table):
        if table not in existing_tables:
            return []
        return [i['name'] for i in inspector.get_indexes(table)]

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
