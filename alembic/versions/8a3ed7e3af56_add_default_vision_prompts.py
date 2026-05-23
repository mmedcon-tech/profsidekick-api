"""add_default_vision_prompts

Revision ID: 8a3ed7e3af56
Revises: eef665a0470b
Create Date: 2025-06-27 01:15:10.708417

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a3ed7e3af56'
down_revision: Union[str, None] = 'eef665a0470b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
