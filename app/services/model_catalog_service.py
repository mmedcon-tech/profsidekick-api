from uuid import UUID

from sqlalchemy.orm import Session

from app.database.models import Avatar3DModel
from app.schemas.model_catalog import Avatar3DModelCreate, Avatar3DModelUpdate


def _serialize_model(model: Avatar3DModel) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "description": model.description,
        "model_type": model.model_type,
        "model_url": model.model_url,
        "thumbnail_url": model.thumbnail_url,
        "file_path": model.model_url,
        "preview_image_path": model.thumbnail_url,
        "gender": model.gender,
        "supported_languages": model.supported_languages,
        "sort_order": model.sort_order,
        "is_active": model.is_active,
        "created_at": model.created_at,
    }


def list_models(db: Session, active_only: bool = False) -> list[dict]:
    query = db.query(Avatar3DModel)
    if active_only:
        query = query.filter(Avatar3DModel.is_active.is_(True))
    models = query.order_by(Avatar3DModel.sort_order, Avatar3DModel.name).all()
    return [_serialize_model(model) for model in models]


def create_model(db: Session, payload: Avatar3DModelCreate) -> dict:
    model = Avatar3DModel(**payload.model_dump())
    db.add(model)
    db.commit()
    db.refresh(model)
    return _serialize_model(model)


def update_model(
    db: Session, model_id: UUID, payload: Avatar3DModelUpdate
) -> dict | None:
    model = db.query(Avatar3DModel).filter(Avatar3DModel.id == model_id).first()
    if model is None:
        return None

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(model, field, value)
    db.commit()
    db.refresh(model)
    return _serialize_model(model)
