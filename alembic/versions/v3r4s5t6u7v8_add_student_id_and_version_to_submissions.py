"""add student_id and version_number to autograder_submissions

Revision ID: v3r4s5t6u7v8
Revises: u2q3r4s5t6u7
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "v3r4s5t6u7v8"
down_revision: Union[str, None] = "u2q3r4s5t6u7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Step 1: Add new nullable columns ─────────────────────────────────────
    op.add_column(
        "autograder_submissions",
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "autograder_submissions",
        sa.Column("version_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "autograder_submissions",
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "autograder_submissions",
        sa.Column("handwritten_file_path", sa.String(500), nullable=True),
    )
    op.add_column(
        "autograder_submissions",
        sa.Column("handwritten_filename", sa.String(255), nullable=True),
    )
    op.add_column(
        "autograder_submissions",
        sa.Column("webassign_file_path", sa.String(500), nullable=True),
    )
    op.add_column(
        "autograder_submissions",
        sa.Column("webassign_filename", sa.String(255), nullable=True),
    )

    op.create_foreign_key(
        "fk_autograder_submissions_student_id",
        "autograder_submissions",
        "students",
        ["student_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_autograder_submissions_submitted_by",
        "autograder_submissions",
        "users",
        ["submitted_by"],
        ["id"],
        ondelete="RESTRICT",
    )

    # ── Step 2: Data migration ────────────────────────────────────────────────
    conn = op.get_bind()

    # Fallback operator: the oldest user in the system (used when student_user_id is NULL)
    fallback_row = conn.execute(
        sa.text("SELECT id FROM users ORDER BY created_at ASC LIMIT 1")
    ).fetchone()
    fallback_user_id = str(fallback_row[0]) if fallback_row else None

    # For each unique student_net_id create one placeholder Student row
    net_ids = conn.execute(
        sa.text(
            "SELECT DISTINCT student_net_id "
            "FROM autograder_submissions "
            "WHERE student_net_id IS NOT NULL"
        )
    ).fetchall()

    for (net_id,) in net_ids:
        # Prefer the user_id already recorded on that student's submissions
        sub = conn.execute(
            sa.text(
                "SELECT student_user_id FROM autograder_submissions "
                "WHERE student_net_id = :net_id AND student_user_id IS NOT NULL "
                "LIMIT 1"
            ),
            {"net_id": net_id},
        ).fetchone()

        operator_id = str(sub[0]) if sub else fallback_user_id
        if not operator_id:
            # No users exist — cannot satisfy NOT NULL on created_by; skip this net_id.
            # The subsequent ALTER COLUMN SET NOT NULL will fail loudly if rows remain NULL.
            continue

        # Insert placeholder student using the sequence for code generation
        student_id_row = conn.execute(
            sa.text(
                "INSERT INTO students (id, student_code, display_name, created_by, created_at) "
                "VALUES ("
                "  gen_random_uuid(), "
                "  'STU-' || LPAD(nextval('student_code_seq')::text, 3, '0'), "
                "  :name, "
                "  :created_by, "
                "  now() "
                ") RETURNING id"
            ),
            {"name": net_id, "created_by": operator_id},
        ).fetchone()

        student_id = str(student_id_row[0])

        # Link all submissions for this net_id to the new Student row.
        # Also backfill handwritten paths from existing file_path / filename columns.
        conn.execute(
            sa.text(
                "UPDATE autograder_submissions "
                "SET student_id            = :sid, "
                "    submitted_by          = COALESCE(student_user_id, :uid), "
                "    handwritten_file_path = file_path, "
                "    handwritten_filename  = filename "
                "WHERE student_net_id = :net_id"
            ),
            {"sid": student_id, "uid": operator_id, "net_id": net_id},
        )

    # Assign version_number: sequential within each student ordered by created_at
    conn.execute(
        sa.text(
            "UPDATE autograder_submissions AS a "
            "SET version_number = sub.rn "
            "FROM ( "
            "    SELECT id, "
            "           ROW_NUMBER() OVER ("
            "               PARTITION BY student_id ORDER BY created_at ASC"
            "           ) AS rn "
            "    FROM autograder_submissions "
            "    WHERE student_id IS NOT NULL "
            ") sub "
            "WHERE a.id = sub.id"
        )
    )

    # ── Step 3: Indexes and unique constraint ─────────────────────────────────
    op.create_index(
        "idx_submissions_student",
        "autograder_submissions",
        ["student_id"],
    )
    # DESC on version_number — use op.execute for precise DDL control
    op.execute(
        "CREATE INDEX idx_submissions_version "
        "ON autograder_submissions(student_id, version_number DESC)"
    )
    op.create_unique_constraint(
        "uq_student_version",
        "autograder_submissions",
        ["student_id", "version_number"],
    )

    # ── Step 4: NOT NULL constraints ─────────────────────────────────────────
    # These will raise a PostgreSQL error if any rows still have NULL values,
    # which is the correct failure mode (means data migration hit an edge case).
    op.alter_column("autograder_submissions", "student_id", nullable=False)
    op.alter_column("autograder_submissions", "version_number", nullable=False)
    op.alter_column("autograder_submissions", "submitted_by", nullable=False)


def downgrade() -> None:
    # Remove NOT NULL constraints first so columns become nullable again
    op.alter_column("autograder_submissions", "submitted_by", nullable=True)
    op.alter_column("autograder_submissions", "version_number", nullable=True)
    op.alter_column("autograder_submissions", "student_id", nullable=True)

    op.drop_constraint("uq_student_version", "autograder_submissions", type_="unique")
    op.execute("DROP INDEX IF EXISTS idx_submissions_version")
    op.drop_index("idx_submissions_student", table_name="autograder_submissions")

    op.drop_constraint(
        "fk_autograder_submissions_submitted_by", "autograder_submissions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_autograder_submissions_student_id", "autograder_submissions", type_="foreignkey"
    )

    op.drop_column("autograder_submissions", "webassign_filename")
    op.drop_column("autograder_submissions", "webassign_file_path")
    op.drop_column("autograder_submissions", "handwritten_filename")
    op.drop_column("autograder_submissions", "handwritten_file_path")
    op.drop_column("autograder_submissions", "submitted_by")
    op.drop_column("autograder_submissions", "version_number")
    op.drop_column("autograder_submissions", "student_id")
    # Note: placeholder Student rows created during upgrade are intentionally
    # not removed — they consumed sequence values and are now part of the data.
