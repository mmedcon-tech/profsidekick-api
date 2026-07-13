"""Prompt System Redesign — Part 2: create avatar_prompt_configs table.

Revision ID: p1002
Revises: p1001
Create Date: 2026-07-04

Creates the per-avatar prompt configuration table that links a publisher's
avatar to a PromptTemplate, with an optional override of the template body.

Three scenarios are represented by the same row shape:

  Scenario                              | prompt_template_id | override_body | is_custom
  ──────────────────────────────────────┼────────────────────┼───────────────┼──────────
  Admin template selected, no edit      | SET                | NULL          | FALSE
  Admin template selected + customised  | SET                | non-null text | FALSE
  Publisher-created custom prompt       | NULL               | non-null text | TRUE

Resolution logic (enforced in PromptResolutionService, not here):
  1. If override_body IS NOT NULL → use override_body
  2. Else if prompt_template_id IS NOT NULL → use PromptTemplate.body
  3. Else → fall back to system default PromptTemplate for this use_case

UNIQUE(avatar_id, use_case) ensures one active configuration per use-case per
avatar.  The upsert endpoint in the publisher API handles "change your mind"
by overwriting the existing row rather than inserting a duplicate.

No data migration is required — existing avatars have no rows here and will
fall back to legacy AvatarTemplateVersion fields / autograder_cache, which
preserves all existing behaviour until the publisher explicitly configures
prompts via the new UI.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision chain
# ---------------------------------------------------------------------------
revision: str = "p1002"
down_revision: str = "p1001"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    op.create_table(
        "avatar_prompt_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        # CASCADE: deleting an avatar removes all its prompt configs automatically.
        sa.Column(
            "avatar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL: deleting an admin template does not remove the config row —
        # the publisher retains their override_body (if any) and the runtime
        # falls through to the system default for this use_case.
        sa.Column(
            "prompt_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Mirrors prompt_templates.use_case — stored here so the resolution
        # service can query without always joining to prompt_templates.
        sa.Column("use_case", sa.String(100), nullable=False),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        # NULL = no override; use the admin template body as-is.
        sa.Column("override_body", sa.Text(), nullable=True),
        # Display label for publisher-created prompts (is_custom=TRUE).
        sa.Column("override_name", sa.Text(), nullable=True),
        # Admin template version at the time the publisher last saved an override.
        # If PromptTemplate.version > pinned_version the UI shows a staleness
        # warning so the publisher can review and re-confirm their override.
        sa.Column("pinned_version", sa.Integer(), nullable=True),
        # TRUE = publisher-created prompt with no admin template as its base.
        # prompt_template_id will be NULL when is_custom=TRUE.
        sa.Column(
            "is_custom",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # One configuration per use-case per avatar.  The publisher API upserts
        # this row rather than inserting a second one for the same (avatar, use_case).
        sa.UniqueConstraint("avatar_id", "use_case", name="uq_avatar_prompt_configs_avatar_use_case"),
    )

    # Resolution service query: WHERE avatar_id = X AND use_case = Y AND is_enabled = TRUE
    op.create_index(
        "ix_avatar_prompt_configs_avatar_use_case",
        "avatar_prompt_configs",
        ["avatar_id", "use_case"],
    )
    # Reverse lookup: "which avatars use this template?" (admin UI / impact analysis)
    op.create_index(
        "ix_avatar_prompt_configs_template_id",
        "avatar_prompt_configs",
        ["prompt_template_id"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    op.drop_index("ix_avatar_prompt_configs_template_id", table_name="avatar_prompt_configs")
    op.drop_index("ix_avatar_prompt_configs_avatar_use_case", table_name="avatar_prompt_configs")
    op.drop_table("avatar_prompt_configs")
