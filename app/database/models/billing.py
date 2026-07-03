import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class CreditBalance(Base):
    __tablename__ = "credit_balances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    balance_credits = Column(Numeric(12, 6), nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class AccessCode(Base):
    __tablename__ = "access_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), nullable=False, unique=True, index=True)
    total_credits = Column(Numeric(12, 6), nullable=False)
    remaining_credits = Column(Numeric(12, 6), nullable=False)
    issued_by = Column(String(255), nullable=False)
    max_redemptions = Column(Integer, nullable=False, default=1)
    redemptions_used = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    redemptions = relationship("AccessCodeRedemption", back_populates="access_code")
    usage_records = relationship("UsageRecord", back_populates="access_code")


class AccessCodeRedemption(Base):
    __tablename__ = "access_code_redemptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    access_code_id = Column(UUID(as_uuid=True), ForeignKey("access_codes.id"), nullable=False)
    redeemed_at = Column(DateTime, default=datetime.utcnow)
    credits_at_redemption = Column(Numeric(12, 6), nullable=False)

    user = relationship("User")
    access_code = relationship("AccessCode", back_populates="redemptions")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_run_id = Column(UUID(as_uuid=True), ForeignKey("session_runs.id"), nullable=True)
    operation_type = Column(String(50), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    raw_cost_usd = Column(Numeric(12, 6), nullable=False)
    platform_fee_usd = Column(Numeric(12, 6), nullable=False)
    total_cost_usd = Column(Numeric(12, 6), nullable=False)
    credits_charged = Column(Numeric(12, 6), nullable=False)
    funded_by = Column(String(20), nullable=False)
    access_code_id = Column(UUID(as_uuid=True), ForeignKey("access_codes.id"), nullable=True)

    # W1A addition
    ai_provider = Column(String(50), nullable=False, default="openai", server_default="openai")

    # Dual voice pipeline billing — caller-supplied key so a retried/duplicate
    # charge request (e.g. a client firing the same TTS-usage POST twice)
    # cannot deduct credits more than once. Nullable: existing token-based
    # charge sites (session_run) don't supply one.
    idempotency_key = Column(String(100), nullable=True, unique=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    session_run = relationship("SessionRun")
    access_code = relationship("AccessCode", back_populates="usage_records")


class PricingConfig(Base):
    __tablename__ = "pricing_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_type = Column(String(50), nullable=False, unique=True, index=True)
    cost_per_1k_input_tokens = Column(Numeric(12, 6), nullable=False, default=0)
    cost_per_1k_output_tokens = Column(Numeric(12, 6), nullable=False, default=0)
    platform_fee_multiplier = Column(Numeric(5, 4), nullable=False, default=1)
    minimum_charge_credits = Column(Numeric(12, 6), nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ProcessedWixOrder(Base):
    """Idempotency guard: prevents double-processing of Wix payment webhooks."""
    __tablename__ = "processed_wix_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(String(255), nullable=False, unique=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    credits_added = Column(Numeric(12, 6), nullable=True)
    raw_payload = Column(JSONB, nullable=True)
    processed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User")


class AutoTopUpSettings(Base):
    """W1B: per-user automatic credit top-up configuration."""
    __tablename__ = "auto_top_up_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    is_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    threshold_credits = Column(Numeric(12, 6), nullable=False, default=10)
    top_up_amount_credits = Column(Numeric(12, 6), nullable=False, default=50)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
