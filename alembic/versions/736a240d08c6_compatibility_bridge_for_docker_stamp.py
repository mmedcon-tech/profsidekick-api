"""compatibility bridge for Docker DB migration stamp

Revision ID: 736a240d08c6
Revises: e4444444444e
Create Date: 2026-06-08 00:00:00.000000

This no-op revision restores a migration ID that exists in some local Docker
Postgres volumes but was not present in the checked-in migration graph.
Those databases already have the schema through e4444444444e, so the revision
only reconnects Alembic history and lets later migrations run normally.
"""

from typing import Sequence, Union

revision: str = "736a240d08c6"
down_revision: Union[str, None] = "e4444444444e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
