"""Add session_mode to sessions; add teaching_prompt + examination_prompt to avatar_template_versions

Revision ID: i0d1e2f3g4h5
Revises: h9c0d1e2f3g4
Create Date: 2026-06-02

Changes:
  sessions:
    + session_mode  String(20)  not null  default 'teaching'  — 'teaching' | 'examination'

  avatar_template_versions:
    + teaching_prompt    Text  nullable  — prompt used when session_mode = 'teaching'
    + examination_prompt Text  nullable  — prompt used when session_mode = 'examination'

  Note: existing conversation_prompt column is preserved for backward compatibility.
  Legacy avatars (created before this migration) continue to use conversation_prompt
  as a fallback when teaching_prompt / examination_prompt are not set.
"""

from alembic import op
import sqlalchemy as sa

revision = "i0d1e2f3g4h5"
down_revision = "h9c0d1e2f3g4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # sessions: add session_mode
    op.add_column(
        "sessions",
        sa.Column(
            "session_mode",
            sa.String(20),
            nullable=False,
            server_default="teaching",
        ),
    )

    # avatar_template_versions: add mode-specific prompt columns
    op.add_column(
        "avatar_template_versions",
        sa.Column("teaching_prompt", sa.Text(), nullable=True),
    )
    op.add_column(
        "avatar_template_versions",
        sa.Column("examination_prompt", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("avatar_template_versions", "examination_prompt")
    op.drop_column("avatar_template_versions", "teaching_prompt")
    op.drop_column("sessions", "session_mode")
