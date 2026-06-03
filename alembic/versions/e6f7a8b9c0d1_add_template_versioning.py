"""add template versioning, roles, and freeze publisher avatars to version

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-01

New tables:
  avatar_template_versions  — immutable prompt snapshots per template
  avatar_template_roles     — roles an admin defines per template

Modified tables:
  avatar_templates  — add category, current_version_id
  avatars           — add template_version_id (freeze at creation version)

Versioning strategy: Option A (frozen instances).
  Existing publisher avatars keep template_version_id = NULL (pre-versioning).
  New avatars receive the current published version id at creation time.
  Admins update templates by creating new version rows; existing avatars are unaffected.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── avatar_template_versions ─────────────────────────────────────────────
    # Must be created BEFORE the FK on avatar_templates.current_version_id
    op.create_table(
        "avatar_template_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("avatar_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("conversation_prompt", sa.Text, nullable=True),
        sa.Column("document_analysis_prompt", sa.Text, nullable=True),
        # draft | published | archived
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("change_notes", sa.Text, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime, nullable=True),
        sa.Column("published_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("template_id", "version_number",
                            name="uq_template_version"),
    )
    op.create_index("ix_avatar_template_versions_template_id",
                    "avatar_template_versions", ["template_id"])
    op.create_index("ix_avatar_template_versions_status",
                    "avatar_template_versions", ["status"])

    # ── avatar_template_roles ─────────────────────────────────────────────────
    op.create_table(
        "avatar_template_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("avatar_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("prompt_context", sa.Text, nullable=True),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_avatar_template_roles_template_id",
                    "avatar_template_roles", ["template_id"])

    # ── modify avatar_templates ───────────────────────────────────────────────
    op.add_column("avatar_templates", sa.Column("category", sa.String(100), nullable=True))
    op.add_column("avatar_templates",
                  sa.Column("current_version_id", postgresql.UUID(as_uuid=True),
                            sa.ForeignKey("avatar_template_versions.id",
                                         name="fk_avatar_templates_current_version",
                                         use_alter=True),
                            nullable=True))

    # ── modify avatars ────────────────────────────────────────────────────────
    # Nullable so pre-existing avatars remain valid (Option A — frozen at creation)
    op.add_column("avatars",
                  sa.Column("template_version_id", postgresql.UUID(as_uuid=True),
                            sa.ForeignKey("avatar_template_versions.id",
                                         name="fk_avatars_template_version"),
                            nullable=True))


def downgrade() -> None:
    op.drop_column("avatars", "template_version_id")
    op.drop_column("avatar_templates", "current_version_id")
    op.drop_column("avatar_templates", "category")
    op.drop_table("avatar_template_roles")
    op.drop_table("avatar_template_versions")
