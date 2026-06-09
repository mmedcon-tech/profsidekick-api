"""Seed session_run pricing config row

Revision ID: o6j7k8l9m0n1
Revises: n5i6j7k8l9m0
Create Date: 2026-06-09

Adds a pricing_configs row for operation_type='session_run' so that
billing_service.charge_usage() can compute costs for realtime sessions.

Rates are based on OpenAI Realtime API audio token pricing with a 20%
platform fee. These can be updated at any time via the admin billing API
without a migration.
"""

import uuid
from alembic import op

revision = "o6j7k8l9m0n1"
down_revision = "n5i6j7k8l9m0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from datetime import datetime

    now = datetime.utcnow()
    op.execute(
        f"""
        INSERT INTO pricing_configs
            (id, operation_type, cost_per_1k_input_tokens, cost_per_1k_output_tokens,
             platform_fee_multiplier, minimum_charge_credits, updated_at)
        SELECT '{uuid.uuid4()}', 'session_run', 0.001500, 0.006000, 1.2000, 0.100000, '{now}'
        WHERE NOT EXISTS (
            SELECT 1 FROM pricing_configs WHERE operation_type = 'session_run'
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM pricing_configs WHERE operation_type = 'session_run'")
