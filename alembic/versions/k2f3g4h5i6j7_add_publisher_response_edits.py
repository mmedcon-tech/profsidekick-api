"""Add publisher_response_edits table

Revision ID: k2f3g4h5i6j7
Revises: j1e2f3g4h5i6
Create Date: 2026-06-02

Changes:
  publisher_response_edits (NEW TABLE):
    id               UUID        primary key
    message_id       UUID FK     → publisher_messages.id  (CASCADE DELETE)  NOT NULL  indexed
    publisher_id     UUID FK     → users.id                                  NOT NULL  indexed
    avatar_id        UUID FK     → avatars.id              (SET NULL)        nullable  indexed
    session_id       String(100) nullable  indexed
    original_content Text        NOT NULL
    edited_content   Text        NOT NULL
    edit_type        String(50)  NOT NULL  server_default='publisher_refinement'
    created_at       DateTime    NOT NULL  server_default=now()

  Matches PublisherResponseEdit in app/database/models.py exactly.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "k2f3g4h5i6j7"
down_revision = "j1e2f3g4h5i6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    def get_cols(table):
        if table not in existing_tables:
            return []
        return [c['name'] for c in inspector.get_columns(table)]

    def get_fks(table):
        if table not in existing_tables:
            return []
        return [f['name'] for f in inspector.get_foreign_keys(table)]

    def get_indexes(table):
        if table not in existing_tables:
            return []
        return [i['name'] for i in inspector.get_indexes(table)]

    op.create_table(
        "publisher_response_edits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("publisher_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "publisher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "avatar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("session_id",        sa.String(100), nullable=True),
        sa.Column("original_content",  sa.Text,        nullable=False),
        sa.Column("edited_content",    sa.Text,        nullable=False),
        sa.Column(
            "edit_type",
            sa.String(50),
            nullable=False,
            server_default="publisher_refinement",
        ),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_publisher_response_edits_message_id",
        "publisher_response_edits",
        ["message_id"],
    )
    op.create_index(
        "ix_publisher_response_edits_publisher_id",
        "publisher_response_edits",
        ["publisher_id"],
    )
    op.create_index(
        "ix_publisher_response_edits_avatar_id",
        "publisher_response_edits",
        ["avatar_id"],
    )
    op.create_index(
        "ix_publisher_response_edits_session_id",
        "publisher_response_edits",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publisher_response_edits_session_id",
        table_name="publisher_response_edits",
    )
    op.drop_index(
        "ix_publisher_response_edits_avatar_id",
        table_name="publisher_response_edits",
    )
    op.drop_index(
        "ix_publisher_response_edits_publisher_id",
        table_name="publisher_response_edits",
    )
    op.drop_index(
        "ix_publisher_response_edits_message_id",
        table_name="publisher_response_edits",
    )
    op.drop_table("publisher_response_edits")
