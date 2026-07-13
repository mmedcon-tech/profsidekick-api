"""Add assessment_id to sae_students and migrate unique constraint

Changes:
  sae_students  + assessment_id (UUID, FK → sae_assessments.id, NOT NULL)
                - UNIQUE(publisher_id, student_number)  [uq_sae_student_publisher_number]
                + UNIQUE(assessment_id, student_number) [uq_sae_student_assessment_number]

Data migration:
  For each distinct publisher_id already in sae_students, one placeholder
  sae_assessments row is inserted (name = "Assessment (migrated)"). All
  existing students for that publisher are then linked to that assessment.
  This preserves every existing student and submission row without data loss.
  Publishers can rename or replace the placeholder assessment from the UI
  after the migration runs.

Revision ID: bb2cc3dd4ee5
Revises: aa1bb2cc3dd4
Create Date: 2026-07-01 00:00:01.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "bb2cc3dd4ee5"
down_revision: Union[str, None] = "aa1bb2cc3dd4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Step 1: add assessment_id as nullable so we can backfill before enforcing NOT NULL ──
    op.add_column(
        "sae_students",
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sae_assessments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_sae_students_assessment_id", "sae_students", ["assessment_id"])

    # ── Step 2: create one placeholder assessment per publisher that already has students ──
    # gen_random_uuid() is available on PostgreSQL 13+ (same assumption as every other
    # migration in this chain that uses it in server_default).
    op.execute("""
        INSERT INTO sae_assessments (id, publisher_id, name, is_active, created_at)
        SELECT
            gen_random_uuid(),
            publisher_id,
            'Assessment (migrated)',
            true,
            NOW()
        FROM (
            SELECT DISTINCT publisher_id
            FROM sae_students
            WHERE assessment_id IS NULL
        ) AS distinct_publishers
    """)

    # ── Step 3: link every existing student to their publisher's placeholder assessment ──
    op.execute("""
        UPDATE sae_students s
        SET assessment_id = a.id
        FROM sae_assessments a
        WHERE a.publisher_id = s.publisher_id
          AND s.assessment_id IS NULL
    """)

    # ── Step 4: enforce NOT NULL now that every row has been backfilled ──
    op.alter_column("sae_students", "assessment_id", nullable=False)

    # ── Step 5: swap unique constraint ──
    # Drop the old per-publisher constraint (publisher_id, student_number).
    op.drop_constraint("uq_sae_student_publisher_number", "sae_students", type_="unique")

    # Create the new per-assessment constraint (assessment_id, student_number).
    op.create_unique_constraint(
        "uq_sae_student_assessment_number",
        "sae_students",
        ["assessment_id", "student_number"],
    )


def downgrade() -> None:
    # Restore the old unique constraint first.
    op.drop_constraint("uq_sae_student_assessment_number", "sae_students", type_="unique")
    op.create_unique_constraint(
        "uq_sae_student_publisher_number",
        "sae_students",
        ["publisher_id", "student_number"],
    )

    # Remove the index and column.
    # Placeholder sae_assessments rows created during upgrade are intentionally
    # kept — removing them here would cascade-delete or violate FK constraints
    # on sae_students rows that were already updated.
    op.drop_index("ix_sae_students_assessment_id", table_name="sae_students")
    op.drop_column("sae_students", "assessment_id")
