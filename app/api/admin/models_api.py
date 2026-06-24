"""W2A: Admin CRUD for the avatar_3d_models catalog."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Avatar3DModel, User
from app.dependencies.auth import require_admin
from app.schemas.schemas import (
    Avatar3DModelCreate,
    Avatar3DModelResponse,
    Avatar3DModelUpdate,
    Avatar3DModelsListResponse,
)

router = APIRouter(prefix="/api/admin/3d-models", tags=["admin-3d-models"])


@router.get("", response_model=Avatar3DModelsListResponse)
def list_3d_models(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    models = db.query(Avatar3DModel).order_by(Avatar3DModel.name).all()
    return Avatar3DModelsListResponse(
        models=[Avatar3DModelResponse.model_validate(m) for m in models],
        total=len(models),
    )


@router.post("", response_model=Avatar3DModelResponse, status_code=status.HTTP_201_CREATED)
def create_3d_model(
    body: Avatar3DModelCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    m = Avatar3DModel(
        name=body.name,
        description=body.description,
        file_path=body.resolved_file_path(),
        preview_image_path=body.resolved_preview_image_path(),
        model_type=body.model_type or "three_js",
        gender=body.gender,
        supported_languages=body.supported_languages or ["en"],
        sort_order=body.sort_order or 0,
        is_active=body.is_active if body.is_active is not None else True,
        created_by=admin.id,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return Avatar3DModelResponse.model_validate(m)


@router.get("/{model_id}", response_model=Avatar3DModelResponse)
def get_3d_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    m = db.query(Avatar3DModel).filter(Avatar3DModel.id == model_id).first()
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="3D model not found")
    return Avatar3DModelResponse.model_validate(m)


@router.patch("/{model_id}", response_model=Avatar3DModelResponse)
def update_3d_model(
    model_id: UUID,
    body: Avatar3DModelUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    m = db.query(Avatar3DModel).filter(Avatar3DModel.id == model_id).first()
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="3D model not found")

    if body.name is not None:
        m.name = body.name
    if body.description is not None:
        m.description = body.description
    resolved_fp = body.file_path or body.model_url
    if resolved_fp is not None:
        m.file_path = resolved_fp
    resolved_pip = body.preview_image_path or body.thumbnail_url
    if resolved_pip is not None:
        m.preview_image_path = resolved_pip
    if body.model_type is not None:
        m.model_type = body.model_type
    if body.gender is not None:
        m.gender = body.gender
    if body.supported_languages is not None:
        m.supported_languages = body.supported_languages
    if body.sort_order is not None:
        m.sort_order = body.sort_order
    if body.is_active is not None:
        m.is_active = body.is_active

    m.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(m)
    return Avatar3DModelResponse.model_validate(m)


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_3d_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    m = db.query(Avatar3DModel).filter(Avatar3DModel.id == model_id).first()
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="3D model not found")
    db.delete(m)
    db.commit()
