"""add country_of_origin and curriculum to sae_students

Revision ID: y1a2b3c4d5e6
Revises: x5u6v7w8y9z0
Create Date: 2026-06-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "y1a2b3c4d5e6"
down_revision: Union[str, None] = "x5u6v7w8y9z0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sae_students",
        sa.Column("country_of_origin", sa.String(100), nullable=True),
    )
    op.add_column(
        "sae_students",
        sa.Column("curriculum", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sae_students", "curriculum")
    op.drop_column("sae_students", "country_of_origin")
