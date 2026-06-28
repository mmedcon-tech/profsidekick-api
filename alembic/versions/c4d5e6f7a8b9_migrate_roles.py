"""migrate roles to publisher and subscriber

Revision ID: c4d5e6f7a8b9
Revises: f3a8b2d1c9e7
Create Date: 2026-05-29

Renames existing role values:
  professor -> publisher
  teacher   -> publisher  (was the erroneous DB default)
  student   -> subscriber

admin is a new role with no existing rows; seeded out of band.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'f3a8b2d1c9e7'
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

    op.execute("UPDATE users SET role = 'publisher'  WHERE role IN ('professor', 'teacher')")
    op.execute("UPDATE users SET role = 'subscriber' WHERE role = 'student'")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'professor' WHERE role = 'publisher'")
    op.execute("UPDATE users SET role = 'student'   WHERE role = 'subscriber'")
