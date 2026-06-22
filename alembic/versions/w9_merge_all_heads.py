"""merge final heads

Revision ID: w9_merge_all_heads
Revises: w4s5t6u7v8w9, w8037
Create Date: 2026-06-22 00:00:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'w9_merge_all_heads'
down_revision: Union[str, tuple] = ('w4s5t6u7v8w9', 'w8037')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass
