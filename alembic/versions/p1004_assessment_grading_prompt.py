"""Prompt System — Phase 3: add grading prompt fields to sae_assessments.

Revision ID: p1004
Revises: p1003
Create Date: 2026-07-05

Adds two columns to sae_assessments:
  grading_prompt_template_id  — optional FK to prompt_templates; the template
                                the publisher chose when creating the assessment.
  grading_prompt_snapshot     — the resolved prompt body frozen at assessment
                                creation time.  All submissions for the same
                                assessment are graded against this exact text,
                                regardless of future edits to the source template.

SET NULL on delete: removing a prompt template does not delete the assessment;
the snapshot column still holds the frozen text, so grading is unaffected.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p1004"
down_revision: str = "p1003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sae_assessments",
        sa.Column(
            "grading_prompt_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "sae_assessments",
        sa.Column("grading_prompt_snapshot", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sae_assessments", "grading_prompt_snapshot")
    op.drop_column("sae_assessments", "grading_prompt_template_id")
