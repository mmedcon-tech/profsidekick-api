"""add program ui fields

Revision ID: w7036
Revises: w7035
Create Date: 2026-06-17 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

revision = "w7036"
down_revision = "w7035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns
    op.add_column("programs", sa.Column("slug", sa.String(length=200), nullable=True))
    op.add_column("programs", sa.Column("theme_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("programs", sa.Column("is_public", sa.Boolean(), server_default=sa.text("false"), nullable=True))
    
    # Populate slug for existing records
    op.execute("UPDATE programs SET slug = gen_random_uuid()::text WHERE slug IS NULL")
    op.alter_column("programs", "slug", nullable=False)
    op.create_index(op.f("ix_programs_slug"), "programs", ["slug"], unique=True)
    
    # Alter name and description to JSONB
    op.execute("ALTER TABLE programs ALTER COLUMN name TYPE JSONB USING jsonb_build_object('en', name, 'ar', name)")
    op.execute("ALTER TABLE programs ALTER COLUMN description TYPE JSONB USING jsonb_build_object('en', description, 'ar', description)")


def downgrade() -> None:
    op.execute("ALTER TABLE programs ALTER COLUMN name TYPE VARCHAR(200) USING name->>'en'")
    op.execute("ALTER TABLE programs ALTER COLUMN description TYPE TEXT USING description->>'en'")
    
    op.drop_index(op.f("ix_programs_slug"), table_name="programs")
    op.drop_column("programs", "is_public")
    op.drop_column("programs", "theme_config")
    op.drop_column("programs", "slug")
