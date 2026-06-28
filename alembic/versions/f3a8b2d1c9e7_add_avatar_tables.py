"""add avatar tables

Revision ID: f3a8b2d1c9e7
Revises: b2a426365d8f
Create Date: 2026-05-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f3a8b2d1c9e7'
down_revision: Union[str, None] = 'b2a426365d8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    def get_cols(table):
        if table not in existing_tables:
            return []
        return [c['name'] for c in inspector.get_columns(table)]

    def get_fks(table):
        if table not in existing_tables:
            return []
        return [f['name'] for f in inspector.get_foreign_keys(table)]

    def get_indexes(table):
        if table not in existing_tables:
            return []
        return [i['name'] for i in inspector.get_indexes(table)]

    op.create_table(
        'avatar_templates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('hidden_system_prompt', sa.Text(), nullable=True),
        sa.Column('default_realtime_prompt', sa.Text(), nullable=True),
        sa.Column('default_vision_prompt', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'avatars',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('template_id', sa.UUID(), nullable=False),
        sa.Column('publisher_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_published', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['template_id'], ['avatar_templates.id'], ),
        sa.ForeignKeyConstraint(['publisher_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'avatar_configurations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('avatar_id', sa.UUID(), nullable=False),
        sa.Column('voice', sa.String(length=100), nullable=True),
        sa.Column('language', sa.String(length=50), nullable=True),
        sa.Column('difficulty_level', sa.String(length=50), nullable=True),
        sa.Column('additional_settings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['avatar_id'], ['avatars.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('avatar_id', name='uq_avatar_configurations_avatar_id')
    )

    op.create_table(
        'rubrics',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('avatar_configuration_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['avatar_configuration_id'], ['avatar_configurations.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'knowledge_documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('avatar_configuration_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('file_name', sa.String(length=255), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('file_type', sa.String(length=50), nullable=True),
        sa.Column('content_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['avatar_configuration_id'], ['avatar_configurations.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'reference_solutions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('avatar_configuration_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('file_name', sa.String(length=255), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('file_type', sa.String(length=50), nullable=True),
        sa.Column('content_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['avatar_configuration_id'], ['avatar_configurations.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    if 'avatar_id' not in get_cols('sessions'):
        op.add_column('sessions',
            sa.Column('avatar_id', sa.UUID(), nullable=True)
        )
    op.create_foreign_key(
        'fk_sessions_avatar_id',
        'sessions', 'avatars',
        ['avatar_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_sessions_avatar_id', 'sessions', type_='foreignkey')
    op.drop_column('sessions', 'avatar_id')
    op.drop_table('reference_solutions')
    op.drop_table('knowledge_documents')
    op.drop_table('rubrics')
    op.drop_table('avatar_configurations')
    op.drop_table('avatars')
    op.drop_table('avatar_templates')
