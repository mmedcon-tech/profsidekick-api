"""Merge main chain (q8l9m0n1o2p3) with legacy compatibility-bridge head (ecce5a45cff0)

Revision ID: r9m0n1o2p3q4
Revises: q8l9m0n1o2p3, ecce5a45cff0
Create Date: 2026-06-09

No-op merge: each branch already applied its own schema changes independently.
This revision exists solely so 'alembic upgrade head' resolves to a single tip.
"""

from typing import Sequence, Union

revision: str = "r9m0n1o2p3q4"
down_revision: Union[str, tuple] = ("q8l9m0n1o2p3", "ecce5a45cff0")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
