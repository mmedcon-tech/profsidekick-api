"""merge_heads

Revision ID: 31cb70510c76
Revises: 9077ce18ff15, abc123456789
Create Date: 2025-10-16 10:25:30.802930

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '31cb70510c76'
down_revision: Union[str, None] = ('9077ce18ff15', 'abc123456789')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
