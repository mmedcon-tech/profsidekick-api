"""Add subscription_cost to avatar_templates; default avatars cost to 3

Revision ID: q8l9m0n1o2p3
Revises: p7k8l9m0n1o2
Create Date: 2026-06-09

Changes:
  - avatar_templates: ADD COLUMN subscription_cost NUMERIC(12,6) NOT NULL DEFAULT 3
  - avatars:          ALTER COLUMN subscription_cost SET DEFAULT 3
    (existing avatars keep their current value; only new ones default to 3)
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "q8l9m0n1o2p3"
down_revision: Union[str, None] = "p7k8l9m0n1o2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add subscription_cost to templates — existing rows get 3
    op.add_column(
        "avatar_templates",
        sa.Column(
            "subscription_cost",
            sa.Numeric(12, 6),
            nullable=False,
            server_default="3",
        ),
    )

    # 2. Change server default on existing avatars column from 0 → 3
    op.alter_column(
        "avatars",
        "subscription_cost",
        server_default="3",
        existing_type=sa.Numeric(12, 6),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "avatars",
        "subscription_cost",
        server_default="0",
        existing_type=sa.Numeric(12, 6),
        existing_nullable=False,
    )
    op.drop_column("avatar_templates", "subscription_cost")
