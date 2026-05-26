"""add processed_wix_orders table

Revision ID: c2222222222c
Revises: b1111111111b
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c2222222222c"
down_revision: Union[str, None] = "b1111111111b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processed_wix_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wix_order_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("credits_added", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processed_wix_orders_wix_order_id",
        "processed_wix_orders",
        ["wix_order_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_processed_wix_orders_wix_order_id",
        table_name="processed_wix_orders",
    )
    op.drop_table("processed_wix_orders")
