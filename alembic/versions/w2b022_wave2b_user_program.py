"""wave2b: add current_program_id FK to users

Revision ID: w2b022
Revises: w2b021
Create Date: 2026-06-14 00:00:10.000000

Wave 2B step 5 — nullable FK addition; safe for live deployments.

Columns added to users:
  current_program_id  UUID FK → programs.id SET NULL nullable
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w2b022"
down_revision = "w2b021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "current_program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("programs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "current_program_id")
