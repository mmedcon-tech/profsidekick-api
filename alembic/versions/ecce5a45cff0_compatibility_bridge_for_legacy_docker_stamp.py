"""compatibility bridge for legacy Docker DB migration stamp

Revision ID: ecce5a45cff0
Revises: f5555555555f
Create Date: 2026-06-08 00:00:00.000000

This no-op revision restores a migration ID that exists in some local Docker
Postgres volumes but was never part of the checked-in migration graph.
Those databases already carry the full current schema (verified through the
head revision f5555555555f), so this revision only reconnects Alembic history
and lets ``alembic upgrade head`` complete as a no-op instead of failing with
"Can't locate revision identified by 'ecce5a45cff0'".

It is intentionally placed at the tip of the graph: fresh databases build the
schema through f5555555555f and then apply this no-op, while pre-existing
volumes stamped ecce5a45cff0 are already at head.
"""

from typing import Sequence, Union

revision: str = "ecce5a45cff0"
down_revision: Union[str, None] = "f5555555555f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
