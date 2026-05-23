"""add_default_vision_prompts

Revision ID: eef665a0470b
Revises: 2807890c1c69
Create Date: 2025-06-27 01:15:03.694304

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eef665a0470b'
down_revision: Union[str, None] = '2807890c1c69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
