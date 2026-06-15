from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import get_current_user
from app.schemas.schemas import (
    AddCreditsRequest,
    AddCreditsResponse,
    BalanceResponse,
    RedeemCodeRequest,
    RedeemCodeResponse,
    UsageHistoryResponse,
    PaginationInfo,
    UsageRecordResponse,
)
from app.services import avatar_access_code_service, billing_service

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/balance", response_model=BalanceResponse)
def get_balance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    info = billing_service.get_active_balance(current_user.id, db)
    return BalanceResponse(
        source=info["source"],
        balance=info["balance"],
        access_code=info.get("access_code"),
        issued_by=info.get("issued_by"),
    )


@router.post("/redeem", response_model=RedeemCodeResponse)
def redeem_code(
    body: RedeemCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Check if this is an avatar access code first (W3 — R48).
    # try_redeem_avatar_code returns None when the code doesn't exist in
    # avatar_access_codes, allowing fall-through to the standard billing flow.
    avatar_result = avatar_access_code_service.try_redeem_avatar_code(
        body.code, current_user, db
    )
    if avatar_result is not None:
        info = billing_service.get_active_balance(current_user.id, db)
        courses_msg = (
            f" Enrolled in {len(avatar_result['courses_enrolled'])} course(s)."
            if avatar_result["courses_enrolled"]
            else ""
        )
        return RedeemCodeResponse(
            success=True,
            credits_available=info["balance"],
            code=avatar_result["code"],
            issued_by=None,
            message=f"Avatar access code redeemed.{courses_msg}",
        )

    # Standard billing credit code
    redemption = billing_service.redeem_access_code(current_user.id, body.code, db)
    info = billing_service.get_active_balance(current_user.id, db)
    return RedeemCodeResponse(
        success=True,
        credits_available=info["balance"],
        code=redemption.access_code.code,
        issued_by=redemption.access_code.issued_by,
        message="Access code redeemed successfully.",
    )


@router.post("/add-credits", response_model=AddCreditsResponse)
def add_credits(
    body: AddCreditsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    credit_balance = billing_service.add_credits(current_user.id, body.amount_usd, db)
    from decimal import Decimal

    credits_added = (
        body.amount_usd * Decimal(str(billing_service.CREDITS_PER_USD))
    ).quantize(Decimal("0.000001"))
    return AddCreditsResponse(
        success=True,
        credits_added=credits_added,
        new_balance=credit_balance.balance_credits,
        message=f"Added credits equivalent to ${body.amount_usd} USD.",
    )


@router.get("/usage", response_model=UsageHistoryResponse)
def get_usage(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = billing_service.get_usage_history(
        current_user.id, db, page=page, limit=limit
    )
    total_pages = (result["total"] + limit - 1) // limit if result["total"] else 1
    return UsageHistoryResponse(
        records=[UsageRecordResponse.model_validate(r) for r in result["records"]],
        total=result["total"],
        pagination=PaginationInfo(
            page=page,
            limit=limit,
            total=result["total"],
            totalPages=total_pages,
        ),
    )
