"""Avatar configuration: LiveAvatar avatar, voice provider, ElevenLabs voice clone."""

from alembic import op
import sqlalchemy as sa

revision = "w5x6y7z8a9b0"
down_revision = "v4w5x6y7z8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatar_configurations", sa.Column("heygen_avatar_id", sa.String(100))
    )
    op.add_column("avatar_configurations", sa.Column("voice_provider", sa.String(20)))
    op.add_column(
        "avatar_configurations", sa.Column("elevenlabs_voice_id", sa.String(100))
    )
    op.add_column(
        "avatar_configurations", sa.Column("voice_clone_consent_at", sa.DateTime())
    )
    op.add_column(
        "avatar_configurations", sa.Column("voice_clone_name", sa.String(200))
    )


def downgrade() -> None:
    op.drop_column("avatar_configurations", "voice_clone_name")
    op.drop_column("avatar_configurations", "voice_clone_consent_at")
    op.drop_column("avatar_configurations", "elevenlabs_voice_id")
    op.drop_column("avatar_configurations", "voice_provider")
    op.drop_column("avatar_configurations", "heygen_avatar_id")
