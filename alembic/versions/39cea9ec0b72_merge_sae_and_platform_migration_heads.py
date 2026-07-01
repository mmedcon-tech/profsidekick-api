"""merge SAE and platform migration heads

Revision ID: 39cea9ec0b72
Revises: 20f2092b2fc8, bb2cc3dd4ee5
Create Date: 2026-07-01 19:44:13.988954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39cea9ec0b72'
down_revision: Union[str, None] = ('20f2092b2fc8', 'bb2cc3dd4ee5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
