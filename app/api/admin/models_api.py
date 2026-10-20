from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import require_admin, require_publisher
from app.schemas.model_catalog import (
    Avatar3DModelCreate,
    Avatar3DModelListResponse,
    Avatar3DModelResponse,
    Avatar3DModelUpdate,
)
from app.services import model_catalog_service


admin_router = APIRouter(prefix="/api/admin/3d-models", tags=["admin-models"])
publisher_router = APIRouter(
    prefix="/api/publisher/3d-models", tags=["publisher-models"]
)


@admin_router.get("", response_model=Avatar3DModelListResponse)
def list_admin_models(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    models = model_catalog_service.list_models(db)
    return {"models": models}


@admin_router.post(
    "", response_model=Avatar3DModelResponse, status_code=status.HTTP_201_CREATED
)
def create_admin_model(
    payload: Avatar3DModelCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return model_catalog_service.create_model(db, payload)


@admin_router.patch("/{model_id}", response_model=Avatar3DModelResponse)
def update_admin_model(
    model_id: UUID,
    payload: Avatar3DModelUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    model = model_catalog_service.update_model(db, model_id, payload)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="3D model not found",
        )
    return model


@publisher_router.get("", response_model=Avatar3DModelListResponse)
def list_publisher_models(
    db: Session = Depends(get_db),
    _: User = Depends(require_publisher),
):
    models = model_catalog_service.list_models(db, active_only=True)
    return {"models": models}
