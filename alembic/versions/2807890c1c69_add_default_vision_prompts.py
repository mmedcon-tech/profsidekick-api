"""add_default_vision_prompts

Revision ID: 2807890c1c69
Revises: 90a962856771
Create Date: 2025-06-27 01:14:59.710669

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2807890c1c69'
down_revision: Union[str, None] = '90a962856771'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
