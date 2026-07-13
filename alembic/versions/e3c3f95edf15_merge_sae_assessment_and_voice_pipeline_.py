"""merge sae assessment and voice pipeline migration heads

Revision ID: e3c3f95edf15
Revises: p1006, v9tts0004
Create Date: 2026-07-13 09:19:50.889612

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3c3f95edf15'
down_revision: Union[str, None] = ('p1006', 'v9tts0004')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
