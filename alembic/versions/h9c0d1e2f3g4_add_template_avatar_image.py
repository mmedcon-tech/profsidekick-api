"""add avatar_image_path to avatar_templates

Revision ID: h9c0d1e2f3g4
Revises: g8b9c0d1e2f3
Create Date: 2026-06-01

Changes:
  avatar_templates:
    + avatar_image_path  String(500)  nullable  — path/URL of the template logo/avatar image
"""

from alembic import op
import sqlalchemy as sa

revision = "h9c0d1e2f3g4"
down_revision = "g8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatar_templates",
        sa.Column("avatar_image_path", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("avatar_templates", "avatar_image_path")
