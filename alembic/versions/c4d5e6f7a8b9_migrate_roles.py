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

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'f3a8b2d1c9e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'publisher'  WHERE role IN ('professor', 'teacher')")
    op.execute("UPDATE users SET role = 'subscriber' WHERE role = 'student'")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'professor' WHERE role = 'publisher'")
    op.execute("UPDATE users SET role = 'student'   WHERE role = 'subscriber'")
