"""merge all heads into a single linear chain

Revision ID: t1p2q3r4s5t6
Revises: ecce5a45cff0, ag002_add_is_active
Create Date: 2026-06-16 00:00:00.000000

Merges two divergent heads:
- ecce5a45cff0 (compatibility bridge / legacy docker stamp tip)
- s0n1o2p3q4r5 (add is_active to autograder_submissions)

Both branches were independently applied via `alembic upgrade heads`.
This no-op revision unifies them so `alembic upgrade head` (singular)
works again and startup migrations proceed without error.
"""

from typing import Sequence, Union

revision: str = "t1p2q3r4s5t6"
down_revision: Union[str, tuple] = ("ecce5a45cff0", "ag002_add_is_active")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
