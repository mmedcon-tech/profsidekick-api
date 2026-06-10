from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import require_admin
from app.schemas.schemas import (
    AccessCodeCreateRequest,
    AccessCodeResponse,
    AccessCodesListResponse,
    AdminAdjustBalanceRequest,
    AdminAdjustBalanceResponse,
    BalanceResponse,
    PricingConfigResponse,
    PricingConfigUpdate,
    UsageHistoryResponse,
    UsageRecordResponse,
    PaginationInfo,
)
from app.services import billing_service

router = APIRouter(prefix="/api/admin/billing", tags=["admin-billing"])


# ── Access codes ──────────────────────────────────────────────────────────────

@router.post("/access-codes", response_model=AccessCodeResponse)
def create_access_code(
    body: AccessCodeCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    code = billing_service.create_access_code(
        issued_by=body.issued_by,
        total_credits=body.total_credits,
        max_redemptions=body.max_redemptions,
        db=db,
        expires_at=body.expires_at,
        code=body.code,
    )
    return AccessCodeResponse.model_validate(code)


@router.get("/access-codes", response_model=AccessCodesListResponse)
def list_access_codes(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    codes = billing_service.list_access_codes(db)
    return AccessCodesListResponse(
        codes=[AccessCodeResponse.model_validate(c) for c in codes],
        total=len(codes),
    )


@router.patch("/access-codes/{code_id}/deactivate", response_model=AccessCodeResponse)
def deactivate_access_code(
    code_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    code = billing_service.deactivate_access_code(code_id, db)
    return AccessCodeResponse.model_validate(code)


# ── Pricing ───────────────────────────────────────────────────────────────────

@router.get("/pricing/{operation_type}", response_model=PricingConfigResponse)
def get_pricing(
    operation_type: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    from app.database.models import PricingConfig

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
    return PricingConfigResponse.model_validate(pricing)


@router.patch("/pricing/{operation_type}", response_model=PricingConfigResponse)
def update_pricing(
    operation_type: str,
    body: PricingConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    pricing = billing_service.update_pricing(
        operation_type=operation_type,
        db=db,
        cost_per_1k_input_tokens=body.cost_per_1k_input_tokens,
        cost_per_1k_output_tokens=body.cost_per_1k_output_tokens,
        platform_fee_multiplier=body.platform_fee_multiplier,
        minimum_charge_credits=body.minimum_charge_credits,
    )
    return PricingConfigResponse.model_validate(pricing)


# ── Per-user balance management ───────────────────────────────────────────────

@router.get("/users/{user_id}/balance", response_model=BalanceResponse)
def admin_get_user_balance(
    user_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    balance = billing_service.get_active_balance(user_id, db)
    return BalanceResponse(
        source=balance["source"],
        balance=balance["balance"],
        access_code=balance.get("access_code"),
        issued_by=balance.get("issued_by"),
    )


@router.post("/users/{user_id}/adjust-balance", response_model=AdminAdjustBalanceResponse)
def admin_adjust_user_balance(
    user_id: UUID,
    body: AdminAdjustBalanceRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = billing_service.adjust_user_balance(
        user_id=user_id,
        delta_credits=body.delta_credits,
        reason=body.reason,
        admin_id=admin.id,
        db=db,
    )
    return AdminAdjustBalanceResponse(**result)


# ── All-user usage ────────────────────────────────────────────────────────────

@router.get("/usage", response_model=UsageHistoryResponse)
def admin_get_all_usage(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user_id: Optional[UUID] = None,
    operation_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = billing_service.get_all_usage(
        db=db,
        page=page,
        limit=limit,
        user_id=user_id,
        operation_type=operation_type,
    )
    total_pages = max(1, (result["total"] + limit - 1) // limit)
    return UsageHistoryResponse(
        records=[UsageRecordResponse.model_validate(r) for r in result["records"]],
        total=result["total"],
        pagination=PaginationInfo(
            page=result["page"],
            limit=result["limit"],
            total=result["total"],
            totalPages=total_pages,
        ),
    )
