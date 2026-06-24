"""W2A: Business logic for publisher avatar variants."""

import uuid
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import Avatar, AvatarVariant, Avatar3DModel


def get_variants(avatar_id: UUID, db: Session) -> list[AvatarVariant]:
    return (
        db.query(AvatarVariant)
        .filter(AvatarVariant.avatar_id == avatar_id)
        .order_by(AvatarVariant.sort_order, AvatarVariant.created_at)
        .all()
    )


def get_variant(avatar_id: UUID, variant_id: UUID, db: Session) -> AvatarVariant:
    v = (
        db.query(AvatarVariant)
        .filter(AvatarVariant.id == variant_id, AvatarVariant.avatar_id == avatar_id)
        .first()
    )
    if not v:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found")
    return v


def create_variant(
    avatar_id: UUID,
    name: str,
    db: Session,
    description: Optional[str] = None,
    model_3d_id: Optional[UUID] = None,
    heygen_avatar_id: Optional[str] = None,
    heygen_voice_id: Optional[str] = None,
    language: Optional[str] = "en",
    is_default: bool = False,
    sort_order: int = 0,
) -> AvatarVariant:
    if model_3d_id:
        model = db.query(Avatar3DModel).filter(Avatar3DModel.id == model_3d_id).first()
        if not model:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="3D model not found")

    if is_default:
        _clear_default(avatar_id, db)

    v = AvatarVariant(
        avatar_id=avatar_id,
        name=name,
        description=description,
        model_3d_id=model_3d_id,
        heygen_avatar_id=heygen_avatar_id,
        heygen_voice_id=heygen_voice_id,
        language=language or "en",
        is_default=is_default,
        sort_order=sort_order,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def update_variant(
    avatar_id: UUID,
    variant_id: UUID,
    db: Session,
    name: Optional[str] = None,
    description: Optional[str] = None,
    model_3d_id: Optional[UUID] = None,
    heygen_avatar_id: Optional[str] = None,
    heygen_voice_id: Optional[str] = None,
    language: Optional[str] = None,
    is_default: Optional[bool] = None,
    sort_order: Optional[int] = None,
) -> AvatarVariant:
    v = get_variant(avatar_id, variant_id, db)

    if model_3d_id is not None:
        model = db.query(Avatar3DModel).filter(Avatar3DModel.id == model_3d_id).first()
        if not model:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="3D model not found")
        v.model_3d_id = model_3d_id

    if name is not None:
        v.name = name
    if description is not None:
        v.description = description
    if heygen_avatar_id is not None:
        v.heygen_avatar_id = heygen_avatar_id
    if heygen_voice_id is not None:
        v.heygen_voice_id = heygen_voice_id
    if language is not None:
        v.language = language
    if sort_order is not None:
        v.sort_order = sort_order
    if is_default is True:
        _clear_default(avatar_id, db, exclude_id=variant_id)
        v.is_default = True
    elif is_default is False:
        v.is_default = False

    v.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(v)
    return v


def delete_variant(avatar_id: UUID, variant_id: UUID, db: Session) -> None:
    v = get_variant(avatar_id, variant_id, db)
    db.delete(v)
    db.commit()


def set_default(avatar_id: UUID, variant_id: UUID, db: Session) -> AvatarVariant:
    _clear_default(avatar_id, db, exclude_id=variant_id)
    v = get_variant(avatar_id, variant_id, db)
    v.is_default = True
    v.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(v)
    return v


def resolve_default_variant(avatar_id: UUID, db: Session) -> Optional[AvatarVariant]:
    return (
        db.query(AvatarVariant)
        .filter(AvatarVariant.avatar_id == avatar_id, AvatarVariant.is_default.is_(True))
        .first()
    )


def build_variant_snapshot(variant: AvatarVariant, db: Optional[Session] = None) -> dict:
    """Build a denormalized snapshot of a variant for storage in session_runs.

    Pass ``db`` to resolve the 3D model URL at snapshot time so the ephemeral
    endpoint can return it without an extra query later.
    """
    model_url: Optional[str] = None
    render_type: str = "static"

    if variant.heygen_avatar_id:
        render_type = "heygen"
    elif variant.model_3d_id:
        render_type = "3d"
        if db is not None:
            m3d = db.query(Avatar3DModel).filter(Avatar3DModel.id == variant.model_3d_id).first()
            if m3d:
                model_url = getattr(m3d, "model_url", None) or getattr(m3d, "file_path", None)

    return {
        "id": str(variant.id),
        "name": variant.name,
        "render_type": render_type,
        "heygen_avatar_id": variant.heygen_avatar_id,
        "heygen_voice_id": variant.heygen_voice_id,
        "language": variant.language,
        "model_3d_id": str(variant.model_3d_id) if variant.model_3d_id else None,
        "model_url": model_url,
    }


def _clear_default(avatar_id: UUID, db: Session, exclude_id: Optional[UUID] = None) -> None:
    q = db.query(AvatarVariant).filter(
        AvatarVariant.avatar_id == avatar_id,
        AvatarVariant.is_default.is_(True),
    )
    if exclude_id:
        q = q.filter(AvatarVariant.id != exclude_id)
    for v in q.all():
        v.is_default = False
        v.updated_at = datetime.utcnow()
