"""add idempotency_key to usage_records

Revision ID: v9tts0003
Revises: v9tts0002
Create Date: 2026-07-03 00:00:02.000000

Lets billing_service.charge_usage() de-duplicate a retried/duplicate charge
request (e.g. a client firing the same TTS-usage POST twice) instead of
deducting credits more than once. Nullable + unique: existing token-based
charge sites (session_run) don't supply a key.
"""

from alembic import op
import sqlalchemy as sa

revision = "v9tts0003"
down_revision = "v9tts0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usage_records",
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_usage_records_idempotency_key",
        "usage_records",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_idempotency_key", table_name="usage_records")
    op.drop_column("usage_records", "idempotency_key")
