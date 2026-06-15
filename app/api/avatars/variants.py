"""W2A: Publisher CRUD for avatar variants."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Avatar, User
from app.dependencies.auth import require_publisher
from app.schemas.schemas import (
    AvatarVariantCreate,
    AvatarVariantResponse,
    AvatarVariantUpdate,
    AvatarVariantsListResponse,
)
from app.services import avatar_variant_service

router = APIRouter(prefix="/api/publisher/avatars/{avatar_id}/variants", tags=["avatar-variants"])


def _get_avatar_and_assert_ownership(avatar_id: UUID, current_user: User, db: Session) -> Avatar:
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    if current_user.role != "admin" and str(avatar.publisher_id) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this avatar")
    return avatar


@router.get("", response_model=AvatarVariantsListResponse)
def list_variants(
    avatar_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    _get_avatar_and_assert_ownership(avatar_id, current_user, db)
    variants = avatar_variant_service.get_variants(avatar_id, db)
    return AvatarVariantsListResponse(
        variants=[AvatarVariantResponse.model_validate(v) for v in variants],
        total=len(variants),
    )


@router.post("", response_model=AvatarVariantResponse, status_code=status.HTTP_201_CREATED)
def create_variant(
    avatar_id: UUID,
    body: AvatarVariantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    _get_avatar_and_assert_ownership(avatar_id, current_user, db)
    variant = avatar_variant_service.create_variant(
        avatar_id=avatar_id,
        name=body.name,
        db=db,
        description=body.description,
        model_3d_id=body.model_3d_id,
        heygen_avatar_id=body.heygen_avatar_id,
        heygen_voice_id=body.heygen_voice_id,
        language=body.language,
        is_default=body.is_default,
        sort_order=body.sort_order,
    )
    return AvatarVariantResponse.model_validate(variant)


@router.patch("/{variant_id}", response_model=AvatarVariantResponse)
def update_variant(
    avatar_id: UUID,
    variant_id: UUID,
    body: AvatarVariantUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    _get_avatar_and_assert_ownership(avatar_id, current_user, db)
    variant = avatar_variant_service.update_variant(
        avatar_id=avatar_id,
        variant_id=variant_id,
        db=db,
        name=body.name,
        description=body.description,
        model_3d_id=body.model_3d_id,
        heygen_avatar_id=body.heygen_avatar_id,
        heygen_voice_id=body.heygen_voice_id,
        language=body.language,
        is_default=body.is_default,
        sort_order=body.sort_order,
    )
    return AvatarVariantResponse.model_validate(variant)


@router.delete("/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_variant(
    avatar_id: UUID,
    variant_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    _get_avatar_and_assert_ownership(avatar_id, current_user, db)
    avatar_variant_service.delete_variant(avatar_id, variant_id, db)


@router.post("/{variant_id}/set-default", response_model=AvatarVariantResponse)
def set_default_variant(
    avatar_id: UUID,
    variant_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_publisher),
):
    _get_avatar_and_assert_ownership(avatar_id, current_user, db)
    variant = avatar_variant_service.set_default(avatar_id, variant_id, db)
    return AvatarVariantResponse.model_validate(variant)
