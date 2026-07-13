"""Backfill missing grading.assessment system prompt.

Revision ID: p1005
Revises: p1004
Create Date: 2026-07-05

p1001 was already applied on existing databases before the fourth system
template (grading.assessment) was added to its seed block.  This migration
inserts that row if it is absent, so environments that ran p1001 early get
the same end state as fresh installs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "p1005"
down_revision: str = "p1004"
branch_labels = None
depends_on = None

_API_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _API_ROOT / "data"


def _read_grading_prompt() -> str:
    path = _DATA_DIR / "grading_prompt.txt"
    if not path.exists():
        raise RuntimeError(
            f"p1005 cannot seed the grading prompt: {path} does not exist."
        )
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError("p1005: data/grading_prompt.txt is empty.")
    return text


def upgrade() -> None:
    bind = op.get_bind()

    # Only insert if no grading.assessment system row exists yet.
    result = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM prompt_templates "
            "WHERE use_case = 'grading.assessment' AND is_system = TRUE"
        )
    )
    if result.scalar() > 0:
        return  # already seeded — nothing to do

    grading_prompt = _read_grading_prompt()
    now = datetime.utcnow()

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
                "name": "Default Grading Prompt",
                "description": (
                    "System default prompt used by the autograder for assessment grading. "
                    "Sourced from data/grading_prompt.txt."
                ),
                "use_case": "grading.assessment",
                "body": grading_prompt,
                "is_system": True,
                "is_active": True,
                "version": 1,
                "created_by": None,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM prompt_templates "
            "WHERE use_case = 'grading.assessment' AND is_system = TRUE"
        )
    )
