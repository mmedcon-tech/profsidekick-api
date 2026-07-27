"""wave2a: create avatar_variants table

Revision ID: w2a016
Revises: w2a015
Create Date: 2026-06-14 00:00:04.000000

Wave 2A step 3 — net-new table; references avatar_3d_models (w2a014).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w2a016"
down_revision = "w2a015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatar_variants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "avatar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "model_3d_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatar_3d_models.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("heygen_avatar_id", sa.String(200), nullable=True),
        sa.Column("heygen_voice_id", sa.String(200), nullable=True),
        sa.Column("language", sa.String(50), nullable=True, server_default="en"),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_avatar_variants_avatar_id", "avatar_variants", ["avatar_id"])
    op.create_index("ix_avatar_variants_is_default", "avatar_variants", ["is_default"])


def downgrade() -> None:
    op.drop_index("ix_avatar_variants_is_default", table_name="avatar_variants")
    op.drop_index("ix_avatar_variants_avatar_id", table_name="avatar_variants")
    op.drop_table("avatar_variants")
