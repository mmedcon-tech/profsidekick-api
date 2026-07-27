"""add is_active to autograder_submissions"""

from alembic import op
import sqlalchemy as sa


revision = "ag002_add_is_active"
down_revision = "ag001_autograder_submissions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "autograder_submissions",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade():
    op.drop_column("autograder_submissions", "is_active")
