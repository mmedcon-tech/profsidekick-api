"""Clinic-scoped peer community: profiles, spaces, posts, reactions, reports.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _fk(name, target, ondelete="CASCADE", nullable=False, index=True):
    return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index)


def upgrade():
    op.create_table(
        "care_community_profiles", _id(), _fk("clinic_id", "clinics.id"), _fk("user_id", "users.id"),
        sa.Column("nickname", sa.String(40), nullable=False), sa.Column("nickname_key", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("clinic_id", "user_id", name="uq_community_profile_user"),
        sa.UniqueConstraint("clinic_id", "nickname_key", name="uq_community_profile_nickname"))
    op.create_table(
        "care_community_spaces", _id(), _fk("clinic_id", "clinics.id"),
        sa.Column("slug", sa.String(60), nullable=False), sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text()), sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("clinic_id", "slug", name="uq_community_space_slug"))
    op.create_table(
        "care_community_posts", _id(), _fk("clinic_id", "clinics.id"), _fk("space_id", "care_community_spaces.id"),
        _fk("parent_id", "care_community_posts.id", nullable=True),
        _fk("profile_id", "care_community_profiles.id", index=False), _fk("author_user_id", "users.id", index=False),
        sa.Column("body", sa.Text(), nullable=False), sa.Column("badge", sa.String(20)),
        sa.Column("medical_flag", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(20), nullable=False, server_default="visible"),
        _fk("moderated_by", "users.id", ondelete="SET NULL", nullable=True, index=False),
        sa.Column("moderated_at", sa.DateTime()),
        sa.Column("is_fictional", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), index=True))
    op.create_table(
        "care_community_reactions", _id(), _fk("post_id", "care_community_posts.id"),
        _fk("user_id", "users.id", index=False), sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("post_id", "user_id", "kind", name="uq_community_reaction"))
    op.create_table(
        "care_community_reports", _id(), _fk("clinic_id", "clinics.id"), _fk("post_id", "care_community_posts.id"),
        _fk("reporter_user_id", "users.id", index=False), sa.Column("reason", sa.String(300)),
        sa.Column("created_at", sa.DateTime()), sa.Column("resolved_at", sa.DateTime()),
        sa.Column("resolution", sa.String(20)))


def downgrade():
    for t in ("care_community_reports", "care_community_reactions", "care_community_posts",
              "care_community_spaces", "care_community_profiles"):
        op.drop_table(t)
