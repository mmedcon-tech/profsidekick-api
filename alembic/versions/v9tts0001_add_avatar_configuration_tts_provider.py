"""add tts_provider to avatar_configurations

Revision ID: v9tts0001
Revises: c829271c20c4
Create Date: 2026-07-03 00:00:00.000000

Dual voice pipeline (Pipeline A hardening) — records which TTS provider the
publisher's configured `voice` value belongs to. Nullable: existing rows are
backfilled at publish time via voice_catalog_service.infer_provider_from_voice()
rather than in this migration, so unpublished/legacy avatars aren't blocked.
"""

from alembic import op
import sqlalchemy as sa

revision = "v9tts0001"
down_revision = "c829271c20c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatar_configurations",
        sa.Column("tts_provider", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("avatar_configurations", "tts_provider")
