"""add course materials and session materials tables

Revision ID: abc123456789
Revises: f2de7958d541
Create Date: 2025-01-13 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "abc123456789"
down_revision: Union[str, None] = "f2de7958d541"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create MaterialType enum
    material_type = postgresql.ENUM(
        "book",
        "article",
        "video",
        "document",
        "link",
        "other",
        name="materialtype",
        create_type=False,
    )
    material_type.create(op.get_bind(), checkfirst=True)

    # Create course_materials table
    op.create_table(
        "course_materials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("material_type", material_type, nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("file_type", sa.String(length=50), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("publisher", sa.String(length=255), nullable=True),
        sa.Column("isbn", sa.String(length=20), nullable=True),
        sa.Column("doi", sa.String(length=100), nullable=True),
        sa.Column(
            "additional_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("is_required", sa.Boolean(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create session_materials table
    op.create_table(
        "session_materials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("course_material_id", sa.UUID(), nullable=False),
        sa.Column("is_included", sa.Boolean(), nullable=True),
        sa.Column("usage_instructions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["course_material_id"],
            ["course_materials.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # Drop session_materials table
    op.drop_table("session_materials")

    # Drop course_materials table
    op.drop_table("course_materials")

    # Drop MaterialType enum
    material_type = postgresql.ENUM(
        "book", "article", "video", "document", "link", "other", name="materialtype"
    )
    material_type.drop(op.get_bind(), checkfirst=True)
