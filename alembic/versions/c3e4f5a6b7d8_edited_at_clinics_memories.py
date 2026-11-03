"""edited_at on clinics and user_memories so seeding never overwrites publisher or patient edits

Revision ID: c3e4f5a6b7d8
Revises: b2d3e4f5a6c7
"""
from alembic import op
import sqlalchemy as sa

revision = "c3e4f5a6b7d8"
down_revision = "b2d3e4f5a6c7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clinics", sa.Column("edited_at", sa.DateTime(), nullable=True))
    op.add_column("user_memories", sa.Column("edited_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("user_memories", "edited_at")
    op.drop_column("clinics", "edited_at")
