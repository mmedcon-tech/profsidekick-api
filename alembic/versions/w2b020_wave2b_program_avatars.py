"""wave2b: create program_avatars table

Revision ID: w2b020
Revises: w2b019
Create Date: 2026-06-14 00:00:08.000000

Wave 2B step 3 — net-new table; references programs and avatars.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "w2b020"
down_revision = "w2b019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "program_avatars",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("programs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "avatar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_unique_constraint(
        "uq_program_avatars_program_avatar",
        "program_avatars",
        ["program_id", "avatar_id"],
    )
    op.create_index("ix_program_avatars_program_id", "program_avatars", ["program_id"])


def downgrade() -> None:
    op.drop_index("ix_program_avatars_program_id", table_name="program_avatars")
    op.drop_constraint("uq_program_avatars_program_avatar", "program_avatars", type_="unique")
    op.drop_table("program_avatars")
