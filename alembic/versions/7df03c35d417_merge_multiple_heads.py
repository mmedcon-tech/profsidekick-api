"""merge_multiple_heads

Revision ID: 7df03c35d417
Revises: 1ed3632f87e8, v9tts0004
Create Date: 2026-07-28 17:18:12.679415

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7df03c35d417'
down_revision: Union[str, None] = ('1ed3632f87e8', 'v9tts0004')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
