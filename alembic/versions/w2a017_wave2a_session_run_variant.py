"""wave2a: add avatar variant tracking to session_runs

Revision ID: w2a017
Revises: w2a016
Create Date: 2026-06-14 00:00:05.000000

Wave 2A step 4 — additive columns; all nullable; safe for live deployments.

Columns added to session_runs:
  avatar_variant_id   UUID FK → avatar_variants.id nullable SET NULL
  variant_snapshot    JSONB nullable — frozen copy of variant at session start
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w2a017"
down_revision = "w2a016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_runs",
        sa.Column(
            "avatar_variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatar_variants.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "session_runs",
        sa.Column("variant_snapshot", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("session_runs", "variant_snapshot")
    op.drop_column("session_runs", "avatar_variant_id")
