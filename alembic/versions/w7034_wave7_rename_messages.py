"""Wave 7: Rename publisher_messages → assistant_messages.

PostgreSQL automatically updates FK constraints that reference the renamed
table, so publisher_message_feedback.message_id and
publisher_response_edits.message_id continue to work without manual FK
surgery. The ORM model and publisher_chat_service references are updated
in the same Wave 7 commit.

Revision ID: w7034
Revises: w7033
"""

from alembic import op

revision = "w7034"
down_revision = "w7033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("publisher_messages", "assistant_messages")


def downgrade() -> None:
    op.rename_table("assistant_messages", "publisher_messages")
