"""Prompt System Redesign — Part 1: create prompt_templates table and seed 4 system rows.

Revision ID: p1001
Revises: cc3dd4ee5ff6
Create Date: 2026-07-04

Creates the global admin-managed prompt template registry.

- prompt_templates: one row per named template; is_system=TRUE rows are
  protected from deletion.  version is bumped on every edit so that
  AvatarPromptConfig.pinned_version can detect staleness.

Seeded system templates:
  1. Default Teaching Prompt      (use_case='session.teaching')
     body sourced from the most-recently-published AvatarTemplateVersion row.
  2. Default Examination Prompt   (use_case='session.examination')   same source.
  3. Default Conversation Prompt  (use_case='session.conversation')  same source.
  4. Default Grading Prompt       (use_case='grading.assessment')
     body sourced from data/grading_prompt.txt at migration time.

If no published AvatarTemplateVersion exists in the DB the session.* templates
are seeded with an empty string — the admin can fill them in via the UI later.

If data/grading_prompt.txt does not exist the migration raises RuntimeError so
the problem is surfaced immediately rather than silently seeding an empty prompt.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision chain
# ---------------------------------------------------------------------------
revision: str = "p1001"
down_revision: str = "cc3dd4ee5ff6"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
# __file__ is  profsidekick-api/alembic/versions/p1001_…py
# three parents up lands at  profsidekick-api/
_API_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _API_ROOT / "data"


def _read_grading_prompt() -> str:
    path = _DATA_DIR / "grading_prompt.txt"
    if not path.exists():
        raise RuntimeError(
            f"Migration p1001 cannot seed the grading prompt: "
            f"{path} does not exist. "
            "Ensure data/grading_prompt.txt is present before running migrations."
        )
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(
            "Migration p1001: data/grading_prompt.txt is empty. "
            "Populate it before running migrations."
        )
    return text


def _read_session_prompts(bind) -> tuple[str, str, str]:
    """
    Return (conversation_prompt, teaching_prompt, examination_prompt) from the
    most-recently-published AvatarTemplateVersion row.

    Falls back to empty strings when no published version exists (new install or
    test environment without template data).
    """
    result = bind.execute(sa.text("""
        SELECT conversation_prompt, teaching_prompt, examination_prompt
        FROM avatar_template_versions
        WHERE status = 'published'
        ORDER BY
            published_at  DESC NULLS LAST,
            created_at    DESC NULLS LAST
        LIMIT 1
    """))
    row = result.fetchone()
    if row is None:
        return ("", "", "")
    return (row[0] or "", row[1] or "", row[2] or "")


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ── Create table ────────────────────────────────────────────────────────
    op.create_table(
        "prompt_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Open-ended string, not a DB enum — new use-cases need only a new row.
        sa.Column("use_case", sa.String(100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        # is_system=TRUE rows may not be deleted (enforced at API layer, not DB).
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        # Bumped on every admin edit; stored in AvatarPromptConfig.pinned_version
        # so the UI can warn publishers when the admin template has changed.
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        # NULL for system-seeded templates (no individual admin "created" them).
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
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
    )

    # Query performance: resolution service always filters by (use_case, is_active)
    # and/or (is_system, is_active).
    op.create_index(
        "ix_prompt_templates_use_case_active",
        "prompt_templates",
        ["use_case", "is_active"],
    )
    op.create_index(
        "ix_prompt_templates_system_active",
        "prompt_templates",
        ["is_system", "is_active"],
    )

    # ── Seed four system templates ───────────────────────────────────────────
    bind = op.get_bind()

    conversation_prompt, teaching_prompt, examination_prompt = (
        _read_session_prompts(bind)
    )
    grading_prompt = _read_grading_prompt()

    now = datetime.utcnow()

    # Use op.bulk_insert with an ad-hoc table object so values are properly
    # parameterised (handles multi-line text, quotes, backslashes, etc.).
    pt = sa.table(
        "prompt_templates",
        sa.column("id"),
        sa.column("name"),
        sa.column("description"),
        sa.column("use_case"),
        sa.column("body"),
        sa.column("is_system"),
        sa.column("is_active"),
        sa.column("version"),
        sa.column("created_by"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )

    op.bulk_insert(
        pt,
        [
            {
                "id": uuid.uuid4(),
                "name": "Default Teaching Prompt",
                "description": (
                    "System default prompt for teaching and consultation sessions. "
                    "Sourced from the most-recently-published avatar template version."
                ),
                "use_case": "session.teaching",
                "body": teaching_prompt,
                "is_system": True,
                "is_active": True,
                "version": 1,
                "created_by": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": uuid.uuid4(),
                "name": "Default Examination Prompt",
                "description": (
                    "System default prompt for examination sessions. "
                    "Sourced from the most-recently-published avatar template version."
                ),
                "use_case": "session.examination",
                "body": examination_prompt,
                "is_system": True,
                "is_active": True,
                "version": 1,
                "created_by": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": uuid.uuid4(),
                "name": "Default Conversation Prompt",
                "description": (
                    "System default fallback prompt for general conversation sessions. "
                    "Sourced from the most-recently-published avatar template version."
                ),
                "use_case": "session.conversation",
                "body": conversation_prompt,
                "is_system": True,
                "is_active": True,
                "version": 1,
                "created_by": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": uuid.uuid4(),
                "name": "Default Grading Prompt",
                "description": (
                    "System default prompt used by the autograder for assessment grading. "
                    "Sourced from data/grading_prompt.txt at migration time. "
                    "Replaces the hardcoded file reference — this row is now the "
                    "authoritative source for the grading prompt."
                ),
                "use_case": "grading.assessment",
                "body": grading_prompt,
                "is_system": True,
                "is_active": True,
                "version": 1,
                "created_by": None,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    op.drop_index("ix_prompt_templates_system_active", table_name="prompt_templates")
    op.drop_index("ix_prompt_templates_use_case_active", table_name="prompt_templates")
    op.drop_table("prompt_templates")
