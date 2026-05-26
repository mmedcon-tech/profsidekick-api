from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database.connection import get_db
from app.schemas.schemas import (
    AccessCodeCreateRequest,
    AccessCodeResponse,
    AccessCodesListResponse,
    PricingConfigResponse,
    PricingConfigUpdate,
)
from app.services import billing_service

router = APIRouter(prefix="/api/admin/billing", tags=["admin-billing"])


def _require_admin(x_admin_secret: str = Header(..., alias="X-Admin-Secret")):
    if not settings.admin_secret or x_admin_secret != settings.admin_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing admin secret.",
        )


@router.post("/access-codes", response_model=AccessCodeResponse, dependencies=[Depends(_require_admin)])
def create_access_code(
    body: AccessCodeCreateRequest,
    db: Session = Depends(get_db),
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


@router.get("/access-codes", response_model=AccessCodesListResponse, dependencies=[Depends(_require_admin)])
def list_access_codes(db: Session = Depends(get_db)):
    codes = billing_service.list_access_codes(db)
    return AccessCodesListResponse(
        codes=[AccessCodeResponse.model_validate(c) for c in codes],
        total=len(codes),
    )


@router.patch(
    "/access-codes/{code_id}/deactivate",
    response_model=AccessCodeResponse,
    dependencies=[Depends(_require_admin)],
)
def deactivate_access_code(code_id: UUID, db: Session = Depends(get_db)):
    code = billing_service.deactivate_access_code(code_id, db)
    return AccessCodeResponse.model_validate(code)


@router.get(
    "/pricing/{operation_type}",
    response_model=PricingConfigResponse,
    dependencies=[Depends(_require_admin)],
)
def get_pricing(operation_type: str, db: Session = Depends(get_db)):
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


@router.patch(
    "/pricing/{operation_type}",
    response_model=PricingConfigResponse,
    dependencies=[Depends(_require_admin)],
)
def update_pricing(
    operation_type: str,
    body: PricingConfigUpdate,
    db: Session = Depends(get_db),
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
