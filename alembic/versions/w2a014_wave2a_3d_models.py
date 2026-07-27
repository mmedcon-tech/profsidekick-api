"""wave2a: create avatar_3d_models catalog table

Revision ID: w2a014
Revises: t1o2p3q4r5s6
Create Date: 2026-06-14 00:00:02.000000

Wave 2A step 1 — net-new table; no existing table altered.
Safe to apply to a live database without downtime.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w2a014"
down_revision = "t1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatar_3d_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("preview_image_path", sa.String(500), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.create_index("ix_avatar_3d_models_is_active", "avatar_3d_models", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_avatar_3d_models_is_active", table_name="avatar_3d_models")
    op.drop_table("avatar_3d_models")
