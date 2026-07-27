"""compatibility bridge for ghost Docker migration stamp

Revision ID: c829271c20c4
Revises: 20f2092b2fc8
Create Date: 2026-06-25 00:00:00.000000

This no-op revision restores a migration ID that exists in some Docker
Postgres volumes but was never committed to the migration graph.
Those databases already carry the full schema through 20f2092b2fc8, so
this file only reconnects Alembic history and lets `alembic upgrade head`
complete without the "Can't locate revision identified by 'c829271c20c4'"
error.
"""

from typing import Sequence, Union

revision: str = "c829271c20c4"
down_revision: Union[str, None] = "20f2092b2fc8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
