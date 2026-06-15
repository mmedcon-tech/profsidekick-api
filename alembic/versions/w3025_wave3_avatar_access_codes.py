"""wave3: create avatar_access_codes table

Revision ID: w3025
Revises: w3024
Create Date: 2026-06-14 00:00:13.000000

Wave 3 step 2 — avatar-level access codes issued by publishers (R46).
Redeeming a code creates an avatar subscription + course enrollments
+ program memberships + optional credit grant (R48).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w3025"
down_revision = "w3024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatar_access_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "avatar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("max_users", sa.Integer(), nullable=False),
        sa.Column("users_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "credits_per_user",
            sa.Numeric(12, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
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
    op.create_index("ix_avatar_access_codes_avatar_id", "avatar_access_codes", ["avatar_id"])
    op.create_index(
        "ix_avatar_access_codes_code", "avatar_access_codes", ["code"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_avatar_access_codes_code", table_name="avatar_access_codes")
    op.drop_index("ix_avatar_access_codes_avatar_id", table_name="avatar_access_codes")
    op.drop_table("avatar_access_codes")
