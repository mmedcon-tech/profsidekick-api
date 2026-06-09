"""merge heads: unify ecce5a45cff0 (courses/billing/rag) and q8l9m0n1o2p3 (subscriptions/credits)

Revision ID: 5869e69a90ff
Revises: ecce5a45cff0, q8l9m0n1o2p3
Create Date: 2026-06-09

This is a no-op merge migration that resolves the multiple-head state created
when two independent feature branches were merged. It introduces no schema
changes; it only joins the two lineages into a single head.
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "5869e69a90ff"
down_revision: Union[str, Sequence[str], None] = ("ecce5a45cff0", "q8l9m0n1o2p3")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
