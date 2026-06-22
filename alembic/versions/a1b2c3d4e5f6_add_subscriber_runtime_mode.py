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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    def get_cols(table):
        if table not in existing_tables:
            return []
        return [c['name'] for c in inspector.get_columns(table)]

    def get_fks(table):
        if table not in existing_tables:
            return []
        return [f['name'] for f in inspector.get_foreign_keys(table)]

    def get_indexes(table):
        if table not in existing_tables:
            return []
        return [i['name'] for i in inspector.get_indexes(table)]

    if "subscriber_runtime_mode" not in get_cols("sessions"):
        op.add_column(
            "sessions",
            sa.Column(
                "subscriber_runtime_mode",
                sa.String(20),
                nullable=False,
                server_default="avatar",
            ),
        )
    if "runtime_mode_used" not in get_cols("session_runs"):
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
