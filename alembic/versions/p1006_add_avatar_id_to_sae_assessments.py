"""Add avatar_id FK to sae_assessments.

Revision ID: p1006
Revises: p1005
Create Date: 2026-07-05

Links a SAEAssessment to the avatar whose grading prompt should be used.
Nullable — existing assessments are unaffected.
SET NULL on avatar delete so the snapshot (already frozen) is preserved.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p1006"
down_revision: str = "p1005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sae_assessments",
        sa.Column(
            "avatar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sae_assessments", "avatar_id")
