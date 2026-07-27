"""wave3: create avatar_access_code_redemptions table

Revision ID: w3026
Revises: w3025
Create Date: 2026-06-14 00:00:14.000000

Wave 3 step 3 — audit log of avatar access code redemptions (R47).
One row per (user, code) pair; unique constraint prevents double-redemption.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w3026"
down_revision = "w3025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatar_access_code_redemptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "avatar_access_code_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatar_access_codes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "redeemed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "credits_granted",
            sa.Numeric(12, 6),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_avatar_code_redemptions_code_id",
        "avatar_access_code_redemptions",
        ["avatar_access_code_id"],
    )
    op.create_index(
        "ix_avatar_code_redemptions_user_id",
        "avatar_access_code_redemptions",
        ["user_id"],
    )
    op.create_unique_constraint(
        "uq_avatar_code_redemption_user_code",
        "avatar_access_code_redemptions",
        ["user_id", "avatar_access_code_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_avatar_code_redemption_user_code",
        "avatar_access_code_redemptions",
        type_="unique",
    )
    op.drop_index(
        "ix_avatar_code_redemptions_user_id",
        table_name="avatar_access_code_redemptions",
    )
    op.drop_index(
        "ix_avatar_code_redemptions_code_id",
        table_name="avatar_access_code_redemptions",
    )
    op.drop_table("avatar_access_code_redemptions")
