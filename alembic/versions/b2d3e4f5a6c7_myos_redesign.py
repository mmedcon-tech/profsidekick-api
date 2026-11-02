"""MYOS redesign: onboarding state, pilot workspaces, twin profile, content source fields.

Revision ID: b2d3e4f5a6c7
Revises: a1c2e3f4b5d6
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "b2d3e4f5a6c7"
down_revision = "a1c2e3f4b5d6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("onboarding_completed_at", sa.DateTime(), nullable=True))
    op.add_column("clinics", sa.Column("is_pilot", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("clinics", sa.Column("languages", JSONB(), nullable=False, server_default='["en"]'))
    op.add_column("doctor_personas", sa.Column("slug", sa.String(100), nullable=True))
    op.add_column("doctor_personas", sa.Column("profile", JSONB(), nullable=False, server_default="{}"))
    op.add_column("doctor_personas", sa.Column("first_messages", JSONB(), nullable=False, server_default="{}"))
    op.create_index("ix_doctor_personas_slug", "doctor_personas", ["slug"], unique=True)
    op.add_column("care_content_items", sa.Column("source_url", sa.String(500), nullable=True))
    op.add_column("care_content_items", sa.Column("source_type", sa.String(30), nullable=True))
    op.add_column("care_content_items", sa.Column("seed_key", sa.String(150), nullable=True))
    op.add_column("care_content_items", sa.Column("edited_at", sa.DateTime(), nullable=True))
    op.create_index("ix_care_content_items_seed_key", "care_content_items", ["seed_key"])


def downgrade():
    op.drop_index("ix_care_content_items_seed_key", table_name="care_content_items")
    for c in ("edited_at", "seed_key", "source_type", "source_url"):
        op.drop_column("care_content_items", c)
    op.drop_index("ix_doctor_personas_slug", table_name="doctor_personas")
    for c in ("first_messages", "profile", "slug"):
        op.drop_column("doctor_personas", c)
    op.drop_column("clinics", "languages")
    op.drop_column("clinics", "is_pilot")
    op.drop_column("users", "onboarding_completed_at")
