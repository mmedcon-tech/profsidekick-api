"""add instructor-edit fields to sae_submissions

Revision ID: x5u6v7w8y9z0
Revises: w4s5t6u7v8w9
Create Date: 2026-06-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "x5u6v7w8y9z0"
down_revision: Union[str, None] = "w4s5t6u7v8w9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sae_submissions",
        sa.Column("edited_result_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "sae_submissions",
        sa.Column("last_edited_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "sae_submissions",
        sa.Column(
            "last_edited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sae_submissions", "last_edited_by")
    op.drop_column("sae_submissions", "last_edited_at")
    op.drop_column("sae_submissions", "edited_result_json")
