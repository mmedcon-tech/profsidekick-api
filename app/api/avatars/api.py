"""
Avatar routes.

Ownership rules enforced here:
  Publisher : create / edit / publish / delete their own avatars and content.
  Subscriber: browse published avatars; launch (create session) handled by
              existing session router — avatar_id is passed as part of sessionDetails.
  Admin     : read-only view of all avatars and configurations.

Prompt fields NEVER appear in any response from this router.
All AI prompts live in AvatarTemplate and are resolved at session-run time.
"""
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import require_admin, require_publisher, require_subscriber
from app.schemas.schemas import (
    AvatarConfigurationCreate,
    AvatarConfigurationResponse,
    AvatarConfigurationUpdate,
    AvatarCreate,
    AvatarListResponse,
    AvatarPublicListResponse,
    AvatarPublicResponse,
    AvatarResponse,
    AvatarSummary,
    AvatarUpdate,
    KnowledgeDocumentResponse,
    ReferenceSolutionResponse,
    RubricCreate,
    RubricResponse,
)
from app.services.avatar_service import AvatarService
from app.services.file_processor import FileProcessor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["avatars"])

avatar_service = AvatarService()
file_processor = FileProcessor()


# ══════════════════════════════════════════════════════════════════
# Publisher — Avatar CRUD
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/publisher/avatars",
    response_model=AvatarResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_avatar(
    data: AvatarCreate,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Owns resource: the calling publisher (publisher_id = current_user.id).
    Validation: template_id must reference an active template; name required.
    """
    try:
        return await avatar_service.create_avatar(db, current_user.id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ create_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating avatar: {e}")


@router.get(
    "/publisher/avatars",
    response_model=AvatarListResponse,
)
async def list_publisher_avatars(
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Returns: only avatars owned by the calling publisher.
    """
    try:
        avatars, total = await avatar_service.list_publisher_avatars(db, current_user.id)
        return AvatarListResponse(
            avatars=[AvatarSummary.model_validate(a) for a in avatars],
            total=total,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ list_publisher_avatars error: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing avatars: {e}")


@router.get(
    "/publisher/avatars/{avatar_id}",
    response_model=AvatarResponse,
)
async def get_publisher_avatar(
    avatar_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Returns: avatar with full configuration (no prompts).
    """
    try:
        avatar = await avatar_service.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=404, detail="Avatar not found")
        if current_user.role != "admin" and str(avatar.publisher_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="You do not own this avatar")
        return avatar
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ get_publisher_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching avatar: {e}")


@router.put(
    "/publisher/avatars/{avatar_id}",
    response_model=AvatarResponse,
)
async def update_avatar(
    avatar_id: UUID,
    data: AvatarUpdate,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Validation: name and description only — no prompt fields allowed.
    """
    try:
        return await avatar_service.update_avatar(db, avatar_id, current_user.id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ update_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating avatar: {e}")


@router.patch(
    "/publisher/avatars/{avatar_id}/publish",
    response_model=AvatarResponse,
)
async def publish_avatar(
    avatar_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Validation: avatar must have an AvatarConfiguration before publish is allowed.
    """
    try:
        return await avatar_service.publish_avatar(db, avatar_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ publish_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error publishing avatar: {e}")


@router.delete(
    "/publisher/avatars/{avatar_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_avatar(
    avatar_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Action: hard delete — cascades to AvatarConfiguration, Rubric,
            KnowledgeDocument, ReferenceSolution.
    """
    try:
        await avatar_service.delete_avatar(db, avatar_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ delete_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting avatar: {e}")


# ══════════════════════════════════════════════════════════════════
# Publisher — AvatarConfiguration
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/publisher/avatars/{avatar_id}/configuration",
    response_model=AvatarConfigurationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_configuration(
    avatar_id: UUID,
    data: AvatarConfigurationCreate,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Validation: avatar must not already have a configuration (use PUT to update).
    No prompt fields — configuration holds only behavioral settings.
    """
    try:
        return await avatar_service.create_configuration(db, avatar_id, current_user.id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ create_configuration error: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating configuration: {e}")


@router.get(
    "/publisher/avatars/{avatar_id}/configuration",
    response_model=AvatarConfigurationResponse,
)
async def get_configuration(
    avatar_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    """
    try:
        return await avatar_service.get_configuration(db, avatar_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ get_configuration error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching configuration: {e}")


@router.put(
    "/publisher/avatars/{avatar_id}/configuration",
    response_model=AvatarConfigurationResponse,
)
async def update_configuration(
    avatar_id: UUID,
    data: AvatarConfigurationUpdate,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Validation: configuration must already exist (use POST to create).
    """
    try:
        return await avatar_service.update_configuration(db, avatar_id, current_user.id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ update_configuration error: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating configuration: {e}")


# ══════════════════════════════════════════════════════════════════
# Publisher — Rubrics
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/publisher/avatars/{avatar_id}/configuration/rubrics",
    response_model=RubricResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_rubric(
    avatar_id: UUID,
    data: RubricCreate,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Validation: AvatarConfiguration must exist first; content is a JSON dict.
    """
    try:
        return await avatar_service.add_rubric(db, avatar_id, current_user.id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ add_rubric error: {e}")
        raise HTTPException(status_code=500, detail=f"Error adding rubric: {e}")


@router.delete(
    "/publisher/avatars/{avatar_id}/configuration/rubrics/{rubric_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_rubric(
    avatar_id: UUID,
    rubric_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar; rubric must belong to this avatar.
    """
    try:
        await avatar_service.delete_rubric(db, avatar_id, rubric_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ delete_rubric error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting rubric: {e}")


# ══════════════════════════════════════════════════════════════════
# Publisher — Knowledge Documents
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/publisher/avatars/{avatar_id}/configuration/knowledge-documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_knowledge_document(
    avatar_id: UUID,
    title: str = Form(...),
    content_text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Accepts: multipart form with title + optional file upload or content_text.
    Validation: AvatarConfiguration must exist first.
    """
    try:
        file_path = file_name = file_type = None
        file_size = None

        if file and file.filename:
            file_content = await file.read()
            file_path = await file_processor.save_uploaded_file(
                file_content, file.filename, f"avatar_{avatar_id}"
            )
            file_name = file.filename
            file_size = len(file_content)
            file_type = file.content_type

        return await avatar_service.add_knowledge_document(
            db, avatar_id, current_user.id,
            title=title,
            content_text=content_text,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ add_knowledge_document error: {e}")
        raise HTTPException(status_code=500, detail=f"Error adding knowledge document: {e}")


@router.delete(
    "/publisher/avatars/{avatar_id}/configuration/knowledge-documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_knowledge_document(
    avatar_id: UUID,
    doc_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar; document must belong to this avatar.
    """
    try:
        await avatar_service.delete_knowledge_document(db, avatar_id, doc_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ delete_knowledge_document error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting knowledge document: {e}")


# ══════════════════════════════════════════════════════════════════
# Publisher — Reference Solutions
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/publisher/avatars/{avatar_id}/configuration/reference-solutions",
    response_model=ReferenceSolutionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_reference_solution(
    avatar_id: UUID,
    title: str = Form(...),
    content_text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Accepts: multipart form with title + optional file upload or content_text.
    Validation: AvatarConfiguration must exist first.
    """
    try:
        file_path = file_name = file_type = None
        file_size = None

        if file and file.filename:
            file_content = await file.read()
            file_path = await file_processor.save_uploaded_file(
                file_content, file.filename, f"avatar_{avatar_id}"
            )
            file_name = file.filename
            file_size = len(file_content)
            file_type = file.content_type

        return await avatar_service.add_reference_solution(
            db, avatar_id, current_user.id,
            title=title,
            content_text=content_text,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ add_reference_solution error: {e}")
        raise HTTPException(status_code=500, detail=f"Error adding reference solution: {e}")


@router.delete(
    "/publisher/avatars/{avatar_id}/configuration/reference-solutions/{solution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_reference_solution(
    avatar_id: UUID,
    solution_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar; solution must belong to this avatar.
    """
    try:
        await avatar_service.delete_reference_solution(db, avatar_id, solution_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ delete_reference_solution error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting reference solution: {e}")


# ══════════════════════════════════════════════════════════════════
# Subscriber — Browse published avatars
# ══════════════════════════════════════════════════════════════════

@router.get(
    "/avatars",
    response_model=AvatarPublicListResponse,
)
async def browse_published_avatars(
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """
    Who can call: Any authenticated user (subscriber, publisher, admin).
    Returns: published avatars only; no configuration or template metadata.
    Use the returned avatar id as avatar_id when creating a session.
    """
    try:
        avatars, total = await avatar_service.list_published_avatars(db)
        return AvatarPublicListResponse(
            avatars=[AvatarPublicResponse.model_validate(a) for a in avatars],
            total=total,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ browse_published_avatars error: {e}")
        raise HTTPException(status_code=500, detail=f"Error browsing avatars: {e}")


@router.get(
    "/avatars/{avatar_id}",
    response_model=AvatarPublicResponse,
)
async def get_published_avatar(
    avatar_id: UUID,
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """
    Who can call: Any authenticated user.
    Returns: single published avatar without configuration details.
    """
    try:
        avatar = await avatar_service.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=404, detail="Avatar not found")
        if not avatar.is_published:
            raise HTTPException(status_code=404, detail="Avatar not found")
        return avatar
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ get_published_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching avatar: {e}")


# ══════════════════════════════════════════════════════════════════
# Admin — Full visibility across all avatars
# ══════════════════════════════════════════════════════════════════

@router.get(
    "/admin/avatars",
    response_model=AvatarListResponse,
)
async def admin_list_all_avatars(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Who can call: Admin only.
    Returns: all avatars regardless of owner or publish state.
    """
    try:
        avatars, total = await avatar_service.list_all_avatars(db)
        return AvatarListResponse(
            avatars=[AvatarSummary.model_validate(a) for a in avatars],
            total=total,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ admin_list_all_avatars error: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing avatars: {e}")


@router.get(
    "/admin/avatars/{avatar_id}",
    response_model=AvatarResponse,
)
async def admin_get_avatar(
    avatar_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Who can call: Admin only.
    Returns: full avatar with configuration and all content assets.
    """
    try:
        avatar = await avatar_service.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=404, detail="Avatar not found")
        return avatar
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ admin_get_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching avatar: {e}")
