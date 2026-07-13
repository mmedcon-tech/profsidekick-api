"""SAE multi-assessment enrollment: partial unique index on sae_students(assessment_id, user_id)

Prevents duplicate activated enrollment for the same (user, assessment) pair.
WHERE user_id IS NOT NULL so pre-created unactivated slots (user_id = NULL) are unaffected.

Revision ID: cc3dd4ee5ff6
Revises: 39cea9ec0b72
Create Date: 2026-07-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cc3dd4ee5ff6"
down_revision: Union[str, None] = "39cea9ec0b72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_sae_students_assessment_user",
        "sae_students",
        ["assessment_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_sae_students_assessment_user", table_name="sae_students")
