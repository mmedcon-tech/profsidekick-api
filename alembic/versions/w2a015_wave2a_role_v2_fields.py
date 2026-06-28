"""wave2a: add v2 HeyGen fields to avatar_template_roles

Revision ID: w2a015
Revises: w2a014
Create Date: 2026-06-14 00:00:03.000000

Wave 2A step 2 — all new columns are nullable; safe for live deployments.

Columns added to avatar_template_roles:
  heygen_avatar_id    VARCHAR(200) nullable
  heygen_voice_id     VARCHAR(200) nullable
  default_language    VARCHAR(50)  nullable
  suggested_3d_model_id UUID FK → avatar_3d_models.id nullable
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w2a015"
down_revision = "w2a014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatar_template_roles",
        sa.Column("heygen_avatar_id", sa.String(200), nullable=True),
    )
    op.add_column(
        "avatar_template_roles",
        sa.Column("heygen_voice_id", sa.String(200), nullable=True),
    )
    op.add_column(
        "avatar_template_roles",
        sa.Column("default_language", sa.String(50), nullable=True),
    )
    op.add_column(
        "avatar_template_roles",
        sa.Column(
            "suggested_3d_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatar_3d_models.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("avatar_template_roles", "suggested_3d_model_id")
    op.drop_column("avatar_template_roles", "default_language")
    op.drop_column("avatar_template_roles", "heygen_voice_id")
    op.drop_column("avatar_template_roles", "heygen_avatar_id")
