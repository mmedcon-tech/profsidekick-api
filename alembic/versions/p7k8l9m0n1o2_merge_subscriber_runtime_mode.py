"""Merge subscriber_runtime_mode branch into main chain

Revision ID: p7k8l9m0n1o2
Revises: o6j7k8l9m0n1, a1b2c3d4e5f6
Create Date: 2026-06-09

Merges the a1b2c3d4e5f6 branch (adds sessions.subscriber_runtime_mode
and session_runs.runtime_mode_used) with the main migration chain so
that both columns are created on startup via alembic upgrade head.
"""

from typing import Sequence, Union

revision: str = "p7k8l9m0n1o2"
down_revision: Union[str, tuple] = ("o6j7k8l9m0n1", "a1b2c3d4e5f6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
