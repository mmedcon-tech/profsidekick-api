"""add is_active to autograder_submissions"""

from alembic import op
import sqlalchemy as sa


revision = "s0n1o2p3q4r5"
down_revision = "r9m0n1o2p3q4"
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
