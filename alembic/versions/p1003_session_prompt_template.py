"""Prompt System — Phase 2: add prompt_template_id to sessions table.

Revision ID: p1003
Revises: p1002
Create Date: 2026-07-04

Adds an optional FK from sessions → prompt_templates so a publisher can
attach a specific prompt template to a session at creation time.

Resolution priority after this change (enforced in PromptResolutionService):
  0. Session.prompt_template_id → PromptTemplate.body   (session-specific)
  1. AvatarPromptConfig.override_body                   (avatar-level override)
  2. AvatarPromptConfig → PromptTemplate                (avatar-level template)
  3. System-default PromptTemplate                      (admin fallback)
  4. None                                               (legacy path)

SET NULL on delete: removing a template does not delete the session; the
session silently falls back to the avatar-level / system-default chain.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p1003"
down_revision: str = "p1002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "prompt_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_sessions_prompt_template_id",
        "sessions",
        ["prompt_template_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_prompt_template_id", table_name="sessions")
    op.drop_column("sessions", "prompt_template_id")
