"""add billing tables

Revision ID: b1111111111b
Revises: 43b7083f77c0
Create Date: 2026-05-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b1111111111b"
down_revision: Union[str, None] = "43b7083f77c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credit_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "balance_credits",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "access_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("total_credits", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column(
            "remaining_credits", sa.Numeric(precision=12, scale=6), nullable=False
        ),
        sa.Column("issued_by", sa.String(length=255), nullable=False),
        sa.Column("max_redemptions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "redemptions_used", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_access_codes_code", "access_codes", ["code"], unique=True)

    op.create_table(
        "access_code_redemptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_code_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "credits_at_redemption",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["access_code_id"], ["access_codes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operation_type", sa.String(length=50), nullable=False),
        sa.Column(
            "input_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "output_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("raw_cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column(
            "platform_fee_usd", sa.Numeric(precision=12, scale=6), nullable=False
        ),
        sa.Column(
            "total_cost_usd", sa.Numeric(precision=12, scale=6), nullable=False
        ),
        sa.Column(
            "credits_charged", sa.Numeric(precision=12, scale=6), nullable=False
        ),
        sa.Column("funded_by", sa.String(length=20), nullable=False),
        sa.Column("access_code_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["access_code_id"], ["access_codes.id"]),
        sa.ForeignKeyConstraint(["session_run_id"], ["session_runs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pricing_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_type", sa.String(length=50), nullable=False),
        sa.Column(
            "cost_per_1k_input_tokens",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cost_per_1k_output_tokens",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "platform_fee_multiplier",
            sa.Numeric(precision=5, scale=4),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "minimum_charge_credits",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pricing_configs_operation_type",
        "pricing_configs",
        ["operation_type"],
        unique=True,
    )

    # Seed default pricing configurations
    # gpt-4o vision: $2.50/1k input, $10.00/1k output (per OpenAI pricing May 2026)
    # gpt-4o-mini chat: $0.15/1k input, $0.60/1k output
    # realtime_token: flat fee tracked via minimum_charge_credits; token cost 0
    # transcription: tracked by audio duration not tokens; flat minimum
    import uuid
    from datetime import datetime

    now = datetime.utcnow()
    op.execute(
        f"""
        INSERT INTO pricing_configs
            (id, operation_type, cost_per_1k_input_tokens, cost_per_1k_output_tokens,
             platform_fee_multiplier, minimum_charge_credits, updated_at)
        VALUES
            ('{uuid.uuid4()}', 'vision',           0.002500, 0.010000, 1.2000, 0.010000, '{now}'),
            ('{uuid.uuid4()}', 'chat',             0.000150, 0.000600, 1.2000, 0.001000, '{now}'),
            ('{uuid.uuid4()}', 'realtime_token',   0.000000, 0.000000, 1.0000, 0.500000, '{now}'),
            ('{uuid.uuid4()}', 'transcription',    0.000000, 0.000000, 1.0000, 0.010000, '{now}')
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM pricing_configs")
    op.drop_index("ix_pricing_configs_operation_type", table_name="pricing_configs")
    op.drop_table("pricing_configs")
    op.drop_table("usage_records")
    op.drop_table("access_code_redemptions")
    op.drop_index("ix_access_codes_code", table_name="access_codes")
    op.drop_table("access_codes")
    op.drop_table("credit_balances")
