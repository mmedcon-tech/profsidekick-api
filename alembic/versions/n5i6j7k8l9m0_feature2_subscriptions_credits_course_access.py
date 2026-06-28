"""Feature 2: subscription credits + course access codes

Revision ID: n5i6j7k8l9m0
Revises: m4h5i6j7k8l9
Create Date: 2026-06-09

Changes:
  avatars               — add subscription_cost NUMERIC DEFAULT 0
  avatar_subscriptions  — add is_active BOOLEAN DEFAULT TRUE, expires_at TIMESTAMP NULL
  courses               — add allow_subscriber_sessions BOOLEAN DEFAULT FALSE
  course_access_codes   — new table (publisher-generated enrollment codes)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'n5i6j7k8l9m0'
down_revision: Union[str, None] = 'm4h5i6j7k8l9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    def col_names(table):
        if table not in existing_tables:
            return []
        return [c['name'] for c in inspector.get_columns(table)]

    # avatars.subscription_cost
    if 'subscription_cost' not in col_names('avatars'):
        op.add_column(
            'avatars',
            sa.Column('subscription_cost', sa.Numeric(12, 6), nullable=False, server_default='0'),
        )

    # avatar_subscriptions.is_active
    if 'is_active' not in col_names('avatar_subscriptions'):
        op.add_column(
            'avatar_subscriptions',
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        )

    # avatar_subscriptions.expires_at
    if 'expires_at' not in col_names('avatar_subscriptions'):
        op.add_column(
            'avatar_subscriptions',
            sa.Column('expires_at', sa.DateTime(), nullable=True),
        )

    # courses.allow_subscriber_sessions
    if 'allow_subscriber_sessions' not in col_names('courses'):
        op.add_column(
            'courses',
            sa.Column('allow_subscriber_sessions', sa.Boolean(), nullable=False, server_default='false'),
        )

    # course_access_codes table
    if 'course_access_codes' not in existing_tables:
        op.create_table(
            'course_access_codes',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('course_id', UUID(as_uuid=True), sa.ForeignKey('courses.id', ondelete='CASCADE'), nullable=False),
            sa.Column('code', sa.String(32), nullable=False, unique=True),
            sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('max_uses', sa.Integer(), nullable=True),
            sa.Column('uses_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_course_access_codes_course_id', 'course_access_codes', ['course_id'])
        op.create_index('ix_course_access_codes_code', 'course_access_codes', ['code'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    def col_names(table):
        if table not in existing_tables:
            return []
        return [c['name'] for c in inspector.get_columns(table)]

    if 'course_access_codes' in existing_tables:
        op.drop_table('course_access_codes')

    if 'allow_subscriber_sessions' in col_names('courses'):
        op.drop_column('courses', 'allow_subscriber_sessions')

    if 'expires_at' in col_names('avatar_subscriptions'):
        op.drop_column('avatar_subscriptions', 'expires_at')

    if 'is_active' in col_names('avatar_subscriptions'):
        op.drop_column('avatar_subscriptions', 'is_active')

    if 'subscription_cost' in col_names('avatars'):
        op.drop_column('avatars', 'subscription_cost')
