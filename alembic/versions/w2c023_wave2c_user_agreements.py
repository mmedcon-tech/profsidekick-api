"""wave2c: create user_agreements table

Revision ID: w2c023
Revises: w2b022
Create Date: 2026-06-14 00:00:11.000000

Wave 2C step 1 — net-new table for GDPR consent tracking.
GDPR columns on users (is_deleted, deleted_at, terms_accepted_at, etc.)
were already applied in Wave 1A (s0n1o2p3q4r5).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w2c023"
down_revision = "w2b022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_agreements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agreement_type", sa.String(50), nullable=False),
        sa.Column(
            "agreed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
    )
    op.create_index("ix_user_agreements_user_id", "user_agreements", ["user_id"])
    op.create_index(
        "ix_user_agreements_type_user",
        "user_agreements",
        ["agreement_type", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_agreements_type_user", table_name="user_agreements")
    op.drop_index("ix_user_agreements_user_id", table_name="user_agreements")
    op.drop_table("user_agreements")
