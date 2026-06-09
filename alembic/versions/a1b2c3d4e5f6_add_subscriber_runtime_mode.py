"""add_subscriber_runtime_mode

Revision ID: a1b2c3d4e5f6
Revises: 2807890c1c69
Create Date: 2026-06-09 00:00:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "2807890c1c69"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "subscriber_runtime_mode",
            sa.String(20),
            nullable=False,
            server_default="avatar",
        ),
    )
    op.add_column(
        "session_runs",
        sa.Column(
            "runtime_mode_used",
            sa.String(20),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("session_runs", "runtime_mode_used")
    op.drop_column("sessions", "subscriber_runtime_mode")
