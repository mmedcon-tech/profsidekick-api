"""wave1a: column additions for provider tracking, avatar control, gdpr, session publish

Revision ID: s0n1o2p3q4r5
Revises: r9m0n1o2p3q4
Create Date: 2026-06-14 00:00:00.000000

Wave 1A — all changes are additive (new nullable columns or new columns with
server defaults).  No existing column is dropped or altered.  Safe to apply
to a live database without downtime.

Columns added:
  session_runs          ai_provider VARCHAR(50) NOT NULL DEFAULT 'openai'
  usage_records         ai_provider VARCHAR(50) NOT NULL DEFAULT 'openai'
  slide_chunks          embedding_provider VARCHAR(50) NOT NULL DEFAULT 'openai'
  knowledge_chunks      embedding_provider VARCHAR(50) NOT NULL DEFAULT 'openai'
  avatars               allow_subscriber_variant_switch BOOLEAN NOT NULL DEFAULT TRUE
  publisher_avatar_profiles  post_session_quiz_enabled BOOLEAN NOT NULL DEFAULT FALSE
  sessions              is_published BOOLEAN NOT NULL DEFAULT FALSE
  sessions              title VARCHAR(255) NULLABLE
  users                 terms_accepted_at TIMESTAMP NULLABLE
  users                 privacy_accepted_at TIMESTAMP NULLABLE
  users                 gdpr_consent_at TIMESTAMP NULLABLE
  users                 marketing_emails_opt_in BOOLEAN NOT NULL DEFAULT FALSE
  users                 is_deleted BOOLEAN NOT NULL DEFAULT FALSE
  users                 deleted_at TIMESTAMP NULLABLE
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "s0n1o2p3q4r5"
down_revision = "r9m0n1o2p3q4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── session_runs ──────────────────────────────────────────────────────────
    op.add_column(
        "session_runs",
        sa.Column(
            "ai_provider",
            sa.String(50),
            nullable=False,
            server_default="openai",
        ),
    )

    # ── usage_records ─────────────────────────────────────────────────────────
    op.add_column(
        "usage_records",
        sa.Column(
            "ai_provider",
            sa.String(50),
            nullable=False,
            server_default="openai",
        ),
    )

    # ── slide_chunks ──────────────────────────────────────────────────────────
    op.add_column(
        "slide_chunks",
        sa.Column(
            "embedding_provider",
            sa.String(50),
            nullable=False,
            server_default="openai",
        ),
    )

    # ── knowledge_chunks ──────────────────────────────────────────────────────
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "embedding_provider",
            sa.String(50),
            nullable=False,
            server_default="openai",
        ),
    )

    # ── avatars ───────────────────────────────────────────────────────────────
    op.add_column(
        "avatars",
        sa.Column(
            "allow_subscriber_variant_switch",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # ── publisher_avatar_profiles ─────────────────────────────────────────────
    op.add_column(
        "publisher_avatar_profiles",
        sa.Column(
            "post_session_quiz_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # ── sessions ──────────────────────────────────────────────────────────────
    op.add_column(
        "sessions",
        sa.Column(
            "is_published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("title", sa.String(255), nullable=True),
    )

    # ── users (GDPR / account lifecycle) ─────────────────────────────────────
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("privacy_accepted_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("gdpr_consent_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "marketing_emails_opt_in",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # users
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "is_deleted")
    op.drop_column("users", "marketing_emails_opt_in")
    op.drop_column("users", "gdpr_consent_at")
    op.drop_column("users", "privacy_accepted_at")
    op.drop_column("users", "terms_accepted_at")

    # sessions
    op.drop_column("sessions", "title")
    op.drop_column("sessions", "is_published")

    # publisher_avatar_profiles
    op.drop_column("publisher_avatar_profiles", "post_session_quiz_enabled")

    # avatars
    op.drop_column("avatars", "allow_subscriber_variant_switch")

    # knowledge_chunks
    op.drop_column("knowledge_chunks", "embedding_provider")

    # slide_chunks
    op.drop_column("slide_chunks", "embedding_provider")

    # usage_records
    op.drop_column("usage_records", "ai_provider")

    # session_runs
    op.drop_column("session_runs", "ai_provider")
