"""Add password reset token fields to users

Revision ID: s1t2u3v4w5x6
Revises: r9m0n1o2p3q4
Create Date: 2026-08-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "s1t2u3v4w5x6"
down_revision: Union[str, None] = "r9m0n1o2p3q4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_reset_token", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("password_reset_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_reset_sent_at")
    op.drop_column("users", "password_reset_token")
