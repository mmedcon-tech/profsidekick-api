"""merge_branches

Revision ID: 20f2092b2fc8
Revises: w2a018, x5u6v7w8y9z0
Create Date: 2026-06-24 10:29:32.783174

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20f2092b2fc8'
down_revision: Union[str, None] = ('w2a018', 'x5u6v7w8y9z0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
