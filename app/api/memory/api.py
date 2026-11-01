"""Authenticated memory controls. Ownership is enforced in the service layer."""

from uuid import UUID
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import get_current_user
from app.schemas.memory import (
    MemoryDashboardResponse,
    MemoryGlobalRequest,
    MemoryConsentRequest,
    MemoryItemRequest,
    MemoryExpertResponse,
)
from app.services import memory_service as service

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=MemoryDashboardResponse)
def get_memory(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    return service.dashboard(db, user.id)


@router.patch("/settings", status_code=204)
def set_global(
    payload: MemoryGlobalRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    service.update_global(db, user.id, payload.enabled)
    return Response(status_code=204)


@router.put("/twins/{avatar_id}/consent", status_code=204)
def set_consent(
    avatar_id: UUID,
    payload: MemoryConsentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    service.update_consent(
        db, user.id, avatar_id, payload.enabled, payload.education_shared
    )
    return Response(status_code=204)


@router.delete("", status_code=204)
def forget_all(
    avatar_id: UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    service.forget(db, user.id, avatar_id)
    return Response(status_code=204)


@router.patch("/items/{item_id}", status_code=204)
def correct_item(
    item_id: UUID,
    payload: MemoryItemRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    service.change_item(db, user.id, item_id, payload.content, payload.status)
    return Response(status_code=204)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(
    item_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    service.change_item(db, user.id, item_id, delete=True)
    return Response(status_code=204)


@router.get("/education/{avatar_id}", response_model=MemoryExpertResponse)
def education_memory(
    avatar_id: UUID,
    student_id: UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return service.education_view(db, user.id, avatar_id, student_id)
