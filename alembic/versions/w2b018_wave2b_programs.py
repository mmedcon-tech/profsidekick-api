"""wave2b: create programs table

Revision ID: w2b018
Revises: w2a017
Create Date: 2026-06-14 00:00:06.000000

Wave 2B step 1 — net-new table; no existing table altered.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w2b018"
down_revision = "w2a017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "programs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "publisher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
    op.create_index("ix_programs_publisher_id", "programs", ["publisher_id"])
    op.create_index("ix_programs_is_active", "programs", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_programs_is_active", table_name="programs")
    op.drop_index("ix_programs_publisher_id", table_name="programs")
    op.drop_table("programs")
