"""wave2a: add model_type, gender, supported_languages, sort_order to avatar_3d_models

Revision ID: w2a018
Revises: w9_merge_all_heads
Create Date: 2026-06-23 00:00:00.000000

Additive columns only — all nullable or with server defaults.
Safe to apply to a live database without downtime.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w2a018"
down_revision = "w9_merge_all_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatar_3d_models",
        sa.Column(
            "model_type",
            sa.String(50),
            nullable=True,
            server_default="three_js",
        ),
    )
    op.add_column(
        "avatar_3d_models",
        sa.Column("gender", sa.String(20), nullable=True),
    )
    op.add_column(
        "avatar_3d_models",
        sa.Column(
            "supported_languages",
            postgresql.JSONB(),
            nullable=True,
            server_default='["en"]',
        ),
    )
    op.add_column(
        "avatar_3d_models",
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("avatar_3d_models", "sort_order")
    op.drop_column("avatar_3d_models", "supported_languages")
    op.drop_column("avatar_3d_models", "gender")
    op.drop_column("avatar_3d_models", "model_type")
