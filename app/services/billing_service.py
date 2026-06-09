import logging
import random
import string
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import (
    AccessCode,
    AccessCodeRedemption,
    CreditBalance,
    PricingConfig,
    UsageRecord,
)

logger = logging.getLogger(__name__)

CREDITS_PER_USD: Decimal = Decimal(settings.credits_per_usd)


def _generate_access_code() -> str:
    chars = string.ascii_uppercase + string.digits
    groups = ["".join(random.choices(chars, k=4)) for _ in range(3)]
    return "-".join(groups)


def get_active_balance(user_id: UUID, db: Session) -> Dict[str, Any]:
    """
    Returns the user's spendable balance.
    Access code balance takes priority over purchased credits when the user
    has a redeemed, non-depleted, non-expired active code.
    """
    redemption = (
        db.query(AccessCodeRedemption)
        .join(AccessCode)
        .filter(
            AccessCodeRedemption.user_id == user_id,
            AccessCode.is_active.is_(True),
            AccessCode.remaining_credits > 0,
        )
        .filter(
            (AccessCode.expires_at.is_(None))
            | (AccessCode.expires_at > datetime.utcnow())
        )
        .order_by(AccessCodeRedemption.redeemed_at.asc())
        .first()
    )

    if redemption and redemption.access_code.remaining_credits > 0:
        return {
            "source": "access_code",
            "balance": Decimal(str(redemption.access_code.remaining_credits)),
            "access_code_id": redemption.access_code_id,
            "access_code": redemption.access_code.code,
            "issued_by": redemption.access_code.issued_by,
        }

    credit_balance = (
        db.query(CreditBalance).filter(CreditBalance.user_id == user_id).first()
    )
    if credit_balance and credit_balance.balance_credits > 0:
        return {
            "source": "purchased",
            "balance": Decimal(str(credit_balance.balance_credits)),
            "access_code_id": None,
            "access_code": None,
            "issued_by": None,
        }

    return {
        "source": "none",
        "balance": Decimal("0"),
        "access_code_id": None,
        "access_code": None,
        "issued_by": None,
    }


def calculate_cost(
    operation_type: str,
    input_tokens: int,
    output_tokens: int,
    db: Session,
) -> Dict[str, Any]:
    """
    Computes raw cost + platform fee for an operation.
    Total is always >= raw_cost (platform_fee_multiplier >= 1.0).
    Minimum charge is enforced from PricingConfig.
    """
    pricing = (
        db.query(PricingConfig)
        .filter(PricingConfig.operation_type == operation_type)
        .first()
    )
    if not pricing:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No pricing config found for operation: {operation_type}",
        )

    cost_per_input = Decimal(str(pricing.cost_per_1k_input_tokens))
    cost_per_output = Decimal(str(pricing.cost_per_1k_output_tokens))
    multiplier = Decimal(str(pricing.platform_fee_multiplier))
    minimum = Decimal(str(pricing.minimum_charge_credits))

    raw_cost_usd = (
        Decimal(input_tokens) / Decimal("1000") * cost_per_input
        + Decimal(output_tokens) / Decimal("1000") * cost_per_output
    )
    total_cost_usd = raw_cost_usd * multiplier
    platform_fee_usd = total_cost_usd - raw_cost_usd

    credits_charged = (total_cost_usd * CREDITS_PER_USD).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    credits_charged = max(credits_charged, minimum)

    return {
        "raw_cost_usd": raw_cost_usd,
        "platform_fee_usd": platform_fee_usd,
        "total_cost_usd": total_cost_usd,
        "credits_charged": credits_charged,
    }


def charge_usage(
    user_id: UUID,
    operation_type: str,
    input_tokens: int,
    output_tokens: int,
    db: Session,
    session_run_id: Optional[UUID] = None,
) -> UsageRecord:
    """
    Atomically deducts credits from the user's active balance and writes a
    UsageRecord.  Balance deduction and record insert share the same
    transaction so that a failed insert rolls back the deduction.

    Raises HTTP 402 if no balance remains across all sources.
    """
    balance_info = get_active_balance(user_id, db)

    if balance_info["source"] == "none":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Insufficient credits. Redeem an access code or add credits to continue."
            ),
        )

    cost = calculate_cost(operation_type, input_tokens, output_tokens, db)
    credits_needed = cost["credits_charged"]

    if balance_info["balance"] < credits_needed:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Insufficient credits. Redeem an access code or add credits to continue."
            ),
        )

    funded_by = balance_info["source"]
    access_code_id = balance_info.get("access_code_id")

    if funded_by == "access_code":
        access_code = (
            db.query(AccessCode)
            .filter(AccessCode.id == access_code_id)
            .with_for_update()
            .first()
        )
        access_code.remaining_credits = (
            Decimal(str(access_code.remaining_credits)) - credits_needed
        )
        access_code.updated_at = datetime.utcnow()
    else:
        credit_balance = (
            db.query(CreditBalance)
            .filter(CreditBalance.user_id == user_id)
            .with_for_update()
            .first()
        )
        credit_balance.balance_credits = (
            Decimal(str(credit_balance.balance_credits)) - credits_needed
        )
        credit_balance.updated_at = datetime.utcnow()

    record = UsageRecord(
        id=uuid.uuid4(),
        user_id=user_id,
        session_run_id=session_run_id,
        operation_type=operation_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        raw_cost_usd=cost["raw_cost_usd"],
        platform_fee_usd=cost["platform_fee_usd"],
        total_cost_usd=cost["total_cost_usd"],
        credits_charged=credits_needed,
        funded_by=funded_by,
        access_code_id=access_code_id,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(
        "Charged %s credits (%s) to user %s for %s",
        credits_needed,
        funded_by,
        user_id,
        operation_type,
    )
    return record


def redeem_access_code(
    user_id: UUID, code_str: str, db: Session
) -> AccessCodeRedemption:
    code_str = code_str.strip().upper()
    access_code = db.query(AccessCode).filter(AccessCode.code == code_str).first()

    if not access_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Access code not found"
        )
    if not access_code.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access code is no longer active",
        )
    if access_code.expires_at and access_code.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access code has expired",
        )
    if access_code.redemptions_used >= access_code.max_redemptions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access code has reached its redemption limit",
        )

    existing = (
        db.query(AccessCodeRedemption)
        .filter(
            AccessCodeRedemption.user_id == user_id,
            AccessCodeRedemption.access_code_id == access_code.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already redeemed this access code",
        )

    redemption = AccessCodeRedemption(
        id=uuid.uuid4(),
        user_id=user_id,
        access_code_id=access_code.id,
        redeemed_at=datetime.utcnow(),
        credits_at_redemption=access_code.remaining_credits,
    )
    access_code.redemptions_used += 1
    access_code.updated_at = datetime.utcnow()

    db.add(redemption)
    db.commit()
    db.refresh(redemption)
    return redemption


def add_credits(user_id: UUID, amount_usd: Decimal, db: Session) -> CreditBalance:
    credits_to_add = (amount_usd * CREDITS_PER_USD).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )

    credit_balance = (
        db.query(CreditBalance).filter(CreditBalance.user_id == user_id).first()
    )
    if credit_balance:
        credit_balance.balance_credits = (
            Decimal(str(credit_balance.balance_credits)) + credits_to_add
        )
        credit_balance.updated_at = datetime.utcnow()
    else:
        credit_balance = CreditBalance(
            id=uuid.uuid4(),
            user_id=user_id,
            balance_credits=credits_to_add,
            updated_at=datetime.utcnow(),
        )
        db.add(credit_balance)

    db.commit()
    db.refresh(credit_balance)
    return credit_balance


# ── Admin functions ────────────────────────────────────────────────────────────


def create_access_code(
    issued_by: str,
    total_credits: Decimal,
    max_redemptions: int,
    db: Session,
    expires_at: Optional[datetime] = None,
    code: Optional[str] = None,
) -> AccessCode:
    if not code:
        code = _generate_access_code()
    code = code.strip().upper()

    existing = db.query(AccessCode).filter(AccessCode.code == code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Access code '{code}' already exists",
        )

    access_code = AccessCode(
        id=uuid.uuid4(),
        code=code,
        total_credits=total_credits,
        remaining_credits=total_credits,
        issued_by=issued_by,
        max_redemptions=max_redemptions,
        redemptions_used=0,
        expires_at=expires_at,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(access_code)
    db.commit()
    db.refresh(access_code)
    return access_code


def list_access_codes(db: Session) -> List[AccessCode]:
    return db.query(AccessCode).order_by(AccessCode.created_at.desc()).all()


def deactivate_access_code(code_id: UUID, db: Session) -> AccessCode:
    access_code = db.query(AccessCode).filter(AccessCode.id == code_id).first()
    if not access_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Access code not found"
        )
    access_code.is_active = False
    access_code.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(access_code)
    return access_code


def update_pricing(
    operation_type: str,
    db: Session,
    cost_per_1k_input_tokens: Optional[Decimal] = None,
    cost_per_1k_output_tokens: Optional[Decimal] = None,
    platform_fee_multiplier: Optional[Decimal] = None,
    minimum_charge_credits: Optional[Decimal] = None,
) -> PricingConfig:
    if platform_fee_multiplier is not None and platform_fee_multiplier < Decimal("1.0"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="platform_fee_multiplier must be >= 1.0 (cannot price below raw cost)",
        )

    pricing = (
        db.query(PricingConfig)
        .filter(PricingConfig.operation_type == operation_type)
        .first()
    )
    if not pricing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No pricing config found for operation: {operation_type}",
        )

    if cost_per_1k_input_tokens is not None:
        pricing.cost_per_1k_input_tokens = cost_per_1k_input_tokens
    if cost_per_1k_output_tokens is not None:
        pricing.cost_per_1k_output_tokens = cost_per_1k_output_tokens
    if platform_fee_multiplier is not None:
        pricing.platform_fee_multiplier = platform_fee_multiplier
    if minimum_charge_credits is not None:
        pricing.minimum_charge_credits = minimum_charge_credits
    pricing.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(pricing)
    return pricing


def get_usage_history(
    user_id: UUID,
    db: Session,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    query = (
        db.query(UsageRecord)
        .filter(UsageRecord.user_id == user_id)
        .order_by(UsageRecord.created_at.desc())
    )
    total = query.count()
    records = query.offset((page - 1) * limit).limit(limit).all()
    return {"records": records, "total": total, "page": page, "limit": limit}


def get_all_usage(
    db: Session,
    page: int = 1,
    limit: int = 20,
    user_id: Optional[UUID] = None,
    operation_type: Optional[str] = None,
) -> Dict[str, Any]:
    query = db.query(UsageRecord).order_by(UsageRecord.created_at.desc())
    if user_id:
        query = query.filter(UsageRecord.user_id == user_id)
    if operation_type:
        query = query.filter(UsageRecord.operation_type == operation_type)
    total = query.count()
    records = query.offset((page - 1) * limit).limit(limit).all()
    return {"records": records, "total": total, "page": page, "limit": limit}


def adjust_user_balance(
    user_id: UUID,
    delta_credits: Decimal,
    reason: str,
    admin_id: UUID,
    db: Session,
) -> Dict[str, Any]:
    """Admin: grant (positive delta) or deduct (negative delta) credits for any user."""
    credit_balance = (
        db.query(CreditBalance)
        .filter(CreditBalance.user_id == user_id)
        .with_for_update()
        .first()
    )

    previous_balance = Decimal("0")
    if credit_balance:
        previous_balance = Decimal(str(credit_balance.balance_credits))
        new_balance = max(previous_balance + delta_credits, Decimal("0"))
        credit_balance.balance_credits = new_balance
        credit_balance.updated_at = datetime.utcnow()
    else:
        new_balance = max(delta_credits, Decimal("0"))
        credit_balance = CreditBalance(
            id=uuid.uuid4(),
            user_id=user_id,
            balance_credits=new_balance,
            updated_at=datetime.utcnow(),
        )
        db.add(credit_balance)

    operation_type = "admin_grant" if delta_credits >= 0 else "admin_deduct"
    record = UsageRecord(
        id=uuid.uuid4(),
        user_id=user_id,
        session_run_id=None,
        operation_type=operation_type,
        input_tokens=0,
        output_tokens=0,
        raw_cost_usd=Decimal("0"),
        platform_fee_usd=Decimal("0"),
        total_cost_usd=Decimal("0"),
        credits_charged=abs(delta_credits),
        funded_by="admin",
        access_code_id=None,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(credit_balance)

    logger.info(
        "Admin %s adjusted balance for user %s: delta=%s reason=%s",
        admin_id, user_id, delta_credits, reason,
    )
    return {
        "previous_balance": previous_balance,
        "new_balance": Decimal(str(credit_balance.balance_credits)),
        "delta_credits": delta_credits,
        "reason": reason,
    }
