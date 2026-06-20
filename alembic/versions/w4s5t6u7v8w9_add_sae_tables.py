"""add self assessment exam tables (sae_students, sae_invitation_tokens, sae_submissions)

Revision ID: w4s5t6u7v8w9
Revises: v3r4s5t6u7v8
Create Date: 2026-06-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "w4s5t6u7v8w9"
down_revision: Union[str, None] = "v3r4s5t6u7v8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── sae_students ──────────────────────────────────────────────────────────
    op.create_table(
        "sae_students",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("student_number", sa.Integer(), nullable=False),
        sa.Column("student_code", sa.String(20), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("publisher_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        # Populated after the student activates their account via invitation link
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_activated", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("has_submitted", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("publisher_id", "student_number",
                            name="uq_sae_student_publisher_number"),
    )
    op.create_index("ix_sae_students_student_code", "sae_students", ["student_code"])
    op.create_index("ix_sae_students_publisher_id", "sae_students", ["publisher_id"])
    op.create_index("ix_sae_students_user_id", "sae_students", ["user_id"])

    # ── sae_invitation_tokens ─────────────────────────────────────────────────
    op.create_table(
        "sae_invitation_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("student_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sae_students.id", ondelete="CASCADE"), nullable=False),
        # secrets.token_urlsafe(32) produces 43-char URL-safe base64 strings
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("is_used", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        # NULL = never expires; publisher can set a deadline
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_unique_index("ux_sae_invitation_tokens_token",
                           "sae_invitation_tokens", ["token"])
    op.create_index("ix_sae_invitation_tokens_student_id",
                    "sae_invitation_tokens", ["student_id"])

    # ── sae_submissions ───────────────────────────────────────────────────────
    # UNIQUE(student_id) enforces the single-submission rule at the DB level.
    op.create_table(
        "sae_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("student_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sae_students.id", ondelete="RESTRICT"),
                  nullable=False, unique=True),
        # True when publisher clicked "Submit on Behalf"
        sa.Column("submitted_by_publisher", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("publisher_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("handwritten_filename", sa.String(255), nullable=True),
        sa.Column("handwritten_file_path", sa.String(500), nullable=True),
        sa.Column("webassign_filename", sa.String(255), nullable=True),
        sa.Column("webassign_file_path", sa.String(500), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("overall_confidence", sa.String(50), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_sae_submissions_student_id", "sae_submissions", ["student_id"])


def downgrade() -> None:
    op.drop_table("sae_submissions")

    op.drop_index("ix_sae_invitation_tokens_student_id",
                  table_name="sae_invitation_tokens")
    op.drop_index("ux_sae_invitation_tokens_token",
                  table_name="sae_invitation_tokens")
    op.drop_table("sae_invitation_tokens")

    op.drop_index("ix_sae_students_user_id", table_name="sae_students")
    op.drop_index("ix_sae_students_publisher_id", table_name="sae_students")
    op.drop_index("ix_sae_students_student_code", table_name="sae_students")
    op.drop_table("sae_students")
