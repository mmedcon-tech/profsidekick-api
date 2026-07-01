"""SAE multi-submission schema — phase 1 foundation columns

No behaviour changes in this migration — only additive schema work.

Changes:
  users                 + token_version (INTEGER, default 1) for future credential-change
                          session invalidation (phase 5).
  sae_students          + submission_count (INTEGER, default 0), backfilled from row count.
  sae_submissions       + submission_number (INTEGER, NOT NULL), backfilled to 1.
                        + is_active (BOOLEAN, NOT NULL, default true), backfilled to true.
                        - UNIQUE(student_id)  →  replaced by UNIQUE(student_id, submission_number).
  sae_invitation_tokens + use_count (INTEGER, default 0), backfilled from is_used.

Revision ID: z2b3c4d5e6f7
Revises: y1a2b3c4d5e6
Create Date: 2026-06-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "z2b3c4d5e6f7"
down_revision: Union[str, None] = "y1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users: token_version for future session invalidation on credential change ─
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
    )

    # ── sae_students: running count of submissions ────────────────────────────────
    op.add_column(
        "sae_students",
        sa.Column("submission_count", sa.Integer(), nullable=False, server_default="0"),
    )
    # Backfill from actual sae_submissions rows so existing data is consistent.
    op.execute("""
        UPDATE sae_students s
        SET submission_count = (
            SELECT COUNT(*) FROM sae_submissions sub WHERE sub.student_id = s.id
        )
    """)

    # ── sae_submissions: per-student version number and active flag ───────────────
    # Step 1: add nullable so we can backfill before enforcing NOT NULL.
    op.add_column(
        "sae_submissions",
        sa.Column("submission_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sae_submissions",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # Step 2: backfill — every existing row is submission #1 and is the active one.
    op.execute("UPDATE sae_submissions SET submission_number = 1 WHERE submission_number IS NULL")

    # Step 3: now safe to make NOT NULL.
    op.alter_column("sae_submissions", "submission_number", nullable=False)

    # Step 4: drop the old single-column unique constraint on student_id.
    # The constraint was created with unique=True in the original create_table call,
    # so PostgreSQL named it sae_submissions_student_id_key.
    # The non-unique lookup index ix_sae_submissions_student_id is kept as-is.
    op.drop_constraint("sae_submissions_student_id_key", "sae_submissions", type_="unique")

    # Step 5: composite unique — one submission_number per student, multiple rows allowed.
    op.create_unique_constraint(
        "uq_sae_submission_student_number",
        "sae_submissions",
        ["student_id", "submission_number"],
    )

    # ── sae_invitation_tokens: track how many times the link has been used ────────
    op.add_column(
        "sae_invitation_tokens",
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
    )
    # Already-used tokens were consumed once (first-use = account creation).
    # We treat them as use_count=1, not 2, because the second use is still available
    # until the student explicitly re-uses the link for credential change.
    # Tokens that were marked is_used=True but never reached a second use keep is_used=True
    # as the permanent-expiry sentinel; use_count records the actual number of activations.
    op.execute("UPDATE sae_invitation_tokens SET use_count = 1 WHERE is_used = TRUE")
    op.execute("UPDATE sae_invitation_tokens SET use_count = 0 WHERE is_used = FALSE")


def downgrade() -> None:
    op.drop_column("sae_invitation_tokens", "use_count")

    op.drop_constraint("uq_sae_submission_student_number", "sae_submissions", type_="unique")
    # Restore the original single-column unique constraint.
    op.create_unique_constraint(
        "sae_submissions_student_id_key", "sae_submissions", ["student_id"]
    )
    op.drop_column("sae_submissions", "is_active")
    op.drop_column("sae_submissions", "submission_number")

    op.drop_column("sae_students", "submission_count")
    op.drop_column("users", "token_version")
