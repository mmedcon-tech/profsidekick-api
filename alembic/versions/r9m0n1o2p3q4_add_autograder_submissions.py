"""add autograder submissions table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ag001_autograder_submissions"
down_revision = "q8l9m0n1o2p3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "autograder_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("student_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("student_net_id", sa.String(length=100), nullable=False),
        sa.Column("student_name", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("overall_confidence", sa.String(length=50), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("result_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("autograder_submissions")