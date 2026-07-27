"""Wave 7: Post-rename index additions for assistant_messages.

Adds an index on assistant_messages.conversation_id (mirrors the old
publisher_messages index). Also adds a composite index on
assistant_conversations(user_id, context_type) for the common analytics
query pattern of 'all conversations for this user of this context type'.

Revision ID: w7035
Revises: w7034
"""

from alembic import op

revision = "w7035"
down_revision = "w7034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite index: all conversations per user filtered by role
    op.create_index(
        "ix_assistant_conversations_user_context",
        "assistant_conversations",
        ["user_id", "context_type"],
    )

    # Index on assistant_messages.conversation_id for message list queries
    op.create_index(
        "ix_assistant_messages_conversation_id",
        "assistant_messages",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_conversation_id", table_name="assistant_messages")
    op.drop_index("ix_assistant_conversations_user_context", table_name="assistant_conversations")
