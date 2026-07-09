"""seed tts_elevenlabs / tts_openai pricing config rows

Revision ID: v9tts0004
Revises: v9tts0003
Create Date: 2026-07-03 00:00:03.000000

Adds pricing_configs rows for the two TTS provider operation types so
billing_service.charge_usage() can meter synthesized characters. Character
counts are passed as `input_tokens` with `output_tokens=0` — the existing
token-shaped columns are reused as a cost-per-1k-characters rate rather than
adding new columns (see billing_service.charge_usage callers in
app/api/voice/api.py). Rates can be updated at any time via the admin
billing API without a migration.
"""

import uuid
from datetime import datetime

from alembic import op

revision = "v9tts0004"
down_revision = "v9tts0003"
branch_labels = None
depends_on = None

# Illustrative starting rates (USD per 1k characters), platform fee applied
# on top. ElevenLabs list pricing is materially higher than OpenAI TTS.
_SEED_ROWS = [
    ("tts_elevenlabs", "0.180000", "1.2000", "0.010000"),
    ("tts_openai", "0.015000", "1.2000", "0.005000"),
]


def upgrade() -> None:
    now = datetime.utcnow()
    for operation_type, cost_per_1k_input, multiplier, minimum in _SEED_ROWS:
        op.execute(
            f"""
            INSERT INTO pricing_configs
                (id, operation_type, cost_per_1k_input_tokens,
                 cost_per_1k_output_tokens, platform_fee_multiplier,
                 minimum_charge_credits, updated_at)
            SELECT '{uuid.uuid4()}', '{operation_type}', {cost_per_1k_input}, 0.000000,
                   {multiplier}, {minimum}, '{now}'
            WHERE NOT EXISTS (
                SELECT 1 FROM pricing_configs WHERE operation_type = '{operation_type}'
            )
            """
        )


def downgrade() -> None:
    for operation_type, *_ in _SEED_ROWS:
        op.execute(
            f"DELETE FROM pricing_configs WHERE operation_type = '{operation_type}'"
        )
