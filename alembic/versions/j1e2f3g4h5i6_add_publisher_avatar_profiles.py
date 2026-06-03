"""Add publisher_avatar_profiles table

Revision ID: j1e2f3g4h5i6
Revises: i0d1e2f3g4h5
Create Date: 2026-06-02

Changes:
  publisher_avatar_profiles (NEW TABLE):
    id                  UUID        primary key
    publisher_avatar_id UUID FK     → avatars.id   (unique — one-to-one)
    teaching_pace       String(50)  nullable  — thorough | balanced | fast
    questioning_style   String(50)  nullable  — socratic | direct | guided
    formality_level     String(50)  nullable  — casual | balanced | formal
    depth_level         String(50)  nullable  — surface | standard | deep
    encouragement_level String(50)  nullable  — high | neutral | minimal
    language_level      String(50)  nullable  — introductory | intermediate | advanced | adaptive
    refined_prompt      Text        nullable  — generated teaching persona prompt
    created_at          DateTime    not null
    updated_at          DateTime    not null
"""

from alembic import op
import sqlalchemy as sa

revision = "j1e2f3g4h5i6"
down_revision = "i0d1e2f3g4h5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publisher_avatar_profiles",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "publisher_avatar_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("teaching_pace",       sa.String(50),  nullable=True),
        sa.Column("questioning_style",   sa.String(50),  nullable=True),
        sa.Column("formality_level",     sa.String(50),  nullable=True),
        sa.Column("depth_level",         sa.String(50),  nullable=True),
        sa.Column("encouragement_level", sa.String(50),  nullable=True),
        sa.Column("language_level",      sa.String(50),  nullable=True),
        sa.Column("refined_prompt",      sa.Text,        nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_publisher_avatar_profiles_publisher_avatar_id",
        "publisher_avatar_profiles",
        ["publisher_avatar_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publisher_avatar_profiles_publisher_avatar_id",
        table_name="publisher_avatar_profiles",
    )
    op.drop_table("publisher_avatar_profiles")
