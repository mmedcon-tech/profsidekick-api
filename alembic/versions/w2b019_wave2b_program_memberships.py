"""wave2b: create program_memberships table

Revision ID: w2b019
Revises: w2b018
Create Date: 2026-06-14 00:00:07.000000

Wave 2B step 2 — net-new table; references programs (w2b018).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w2b019"
down_revision = "w2b018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "program_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("programs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(50),
            nullable=False,
            server_default="member",
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_unique_constraint(
        "uq_program_memberships_program_user",
        "program_memberships",
        ["program_id", "user_id"],
    )
    op.create_index("ix_program_memberships_user_id", "program_memberships", ["user_id"])
    op.create_index("ix_program_memberships_program_id", "program_memberships", ["program_id"])


def downgrade() -> None:
    op.drop_index("ix_program_memberships_program_id", table_name="program_memberships")
    op.drop_index("ix_program_memberships_user_id", table_name="program_memberships")
    op.drop_constraint("uq_program_memberships_program_user", "program_memberships", type_="unique")
    op.drop_table("program_memberships")
