"""Wave 7: Rename publisher_conversations → assistant_conversations.

Adds context_type (default 'publisher'), renames publisher_id → user_id,
adds program_id (nullable FK → programs). Backfills context_type and user_id
for existing rows. This is the only rename-based migration in the roadmap;
run against a staging copy with production data before production deployment.

Revision ID: w7033
Revises: w6028
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "w7033"
down_revision = "w6028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Rename the table
    op.rename_table("publisher_conversations", "assistant_conversations")

    # 2. Add context_type column with server default
    op.add_column(
        "assistant_conversations",
        sa.Column(
            "context_type",
            sa.String(50),
            nullable=False,
            server_default="publisher",
        ),
    )

    # 3. Rename publisher_id → user_id (preserves all existing data)
    op.alter_column(
        "assistant_conversations",
        "publisher_id",
        new_column_name="user_id",
    )

    # 4. Add program_id nullable FK
    op.add_column(
        "assistant_conversations",
        sa.Column("program_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_assistant_conversations_program_id",
        "assistant_conversations",
        "programs",
        ["program_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 5. Index on user_id (was indexed as publisher_id; recreate under new name)
    op.create_index(
        "ix_assistant_conversations_user_id",
        "assistant_conversations",
        ["user_id"],
    )

    # 6. Index on context_type for filtered queries
    op.create_index(
        "ix_assistant_conversations_context_type",
        "assistant_conversations",
        ["context_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_conversations_context_type", table_name="assistant_conversations")
    op.drop_index("ix_assistant_conversations_user_id", table_name="assistant_conversations")
    op.drop_constraint("fk_assistant_conversations_program_id", "assistant_conversations", type_="foreignkey")
    op.drop_column("assistant_conversations", "program_id")
    op.alter_column("assistant_conversations", "user_id", new_column_name="publisher_id")
    op.drop_column("assistant_conversations", "context_type")
    op.rename_table("assistant_conversations", "publisher_conversations")
