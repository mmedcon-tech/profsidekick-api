"""Add avatar_subscriptions table

Revision ID: l3g4h5i6j7k8
Revises: k2f3g4h5i6j7
Create Date: 2026-06-02

Changes:
  avatar_subscriptions (NEW TABLE):
    id              UUID        primary key
    subscriber_id   UUID FK     → users.id    (CASCADE DELETE)  NOT NULL  indexed
    avatar_id       UUID FK     → avatars.id  (CASCADE DELETE)  NOT NULL  indexed
    subscribed_at   DateTime    NOT NULL  server_default=now()
    UNIQUE (subscriber_id, avatar_id)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "l3g4h5i6j7k8"
down_revision = "k2f3g4h5i6j7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatar_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subscriber_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "avatar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscribed_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("subscriber_id", "avatar_id", name="uq_avatar_subscription"),
    )
    op.create_index(
        "ix_avatar_subscriptions_subscriber_id",
        "avatar_subscriptions",
        ["subscriber_id"],
    )
    op.create_index(
        "ix_avatar_subscriptions_avatar_id",
        "avatar_subscriptions",
        ["avatar_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_avatar_subscriptions_avatar_id", table_name="avatar_subscriptions")
    op.drop_index("ix_avatar_subscriptions_subscriber_id", table_name="avatar_subscriptions")
    op.drop_table("avatar_subscriptions")
