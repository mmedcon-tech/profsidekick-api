"""
Avatar Template routes.

Ownership rules:
  - Admin    : full CRUD including prompts, versions, roles
  - Publisher: read-only list (no prompt fields) to select a template when creating an avatar
  - Subscriber: no access
"""
import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import require_admin, require_publisher
from app.schemas.schemas import (
    AvatarTemplateCreate,
    AvatarTemplateDetailResponse,
    AvatarTemplatePricingUpdate,
    AvatarTemplateResponse,
    AvatarTemplateRoleCreate,
    AvatarTemplateRoleResponse,
    AvatarTemplateRoleUpdate,
    AvatarTemplateSummary,
    AvatarTemplateUpdate,
    AvatarTemplateVersionCreate,
    AvatarTemplateVersionResponse,
    RoleReorderRequest,
    TemplateImageResponse,
    TemplateDashboardStats,
    TemplatePublisherRow,
    TemplateCourseRow,
    TemplateSessionRunRow,
)
from app.database.models import AvatarTemplate
from app.services.avatar_template_service import AvatarTemplateService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["avatar-templates"])

template_service = AvatarTemplateService()


# ══════════════════════════════════════════════════════════════════
# Admin — template CRUD
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/admin/avatar-templates",
    response_model=AvatarTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    data: AvatarTemplateCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return await template_service.create_template(db, current_user.id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_template error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/admin/avatar-templates",
    response_model=List[AvatarTemplateResponse],
)
async def list_templates(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return await template_service.list_templates(db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_templates error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/admin/avatar-templates/{template_id}",
    response_model=AvatarTemplateDetailResponse,
)
async def get_template(
    template_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        template = await template_service.get_template(db, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        # Attach full version history for detail view
        template.versions = sorted(template.versions, key=lambda v: v.version_number, reverse=True)
        return template
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_template error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put(
    "/admin/avatar-templates/{template_id}",
    response_model=AvatarTemplateResponse,
)
async def update_template(
    template_id: UUID,
    data: AvatarTemplateUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return await template_service.update_template(db, template_id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"update_template error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/admin/avatar-templates/{template_id}",
    response_model=AvatarTemplateResponse,
)
async def archive_template(
    template_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return await template_service.archive_template(db, template_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"archive_template error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════
# Admin — template pricing
# ══════════════════════════════════════════════════════════════════

@router.patch(
    "/admin/avatar-templates/{template_id}/pricing",
    response_model=AvatarTemplateResponse,
)
async def set_template_pricing(
    template_id: UUID,
    data: AvatarTemplatePricingUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Set the subscription cost on a template. Inherited by new avatars at creation time."""
    try:
        template = db.query(AvatarTemplate).filter(AvatarTemplate.id == template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        template.subscription_cost = data.subscription_cost
        db.commit()
        return await template_service.get_template(db, template_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"set_template_pricing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════
# Admin — version management (draft / publish)
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/admin/avatar-templates/{template_id}/versions",
    response_model=AvatarTemplateVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_draft(
    template_id: UUID,
    data: AvatarTemplateVersionCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Save prompts as a new draft version. Existing published version is unaffected."""
    try:
        return await template_service.save_draft(db, template_id, data, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"save_draft error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch(
    "/admin/avatar-templates/{template_id}/versions/{version_id}/publish",
    response_model=AvatarTemplateVersionResponse,
)
async def publish_version(
    template_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Publish a draft version.
    Previous published version is archived.
    New publisher avatars will inherit this version's prompts.
    Existing publisher avatars remain frozen at the version they were created from (Option A).
    """
    try:
        return await template_service.publish_version(db, template_id, version_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"publish_version error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/admin/avatar-templates/{template_id}/versions",
    response_model=List[AvatarTemplateVersionResponse],
)
async def list_versions(
    template_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return await template_service.list_versions(db, template_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_versions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════
# Admin — role management
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/admin/avatar-templates/{template_id}/roles",
    response_model=AvatarTemplateRoleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_role(
    template_id: UUID,
    data: AvatarTemplateRoleCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return await template_service.create_role(db, template_id, data, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_role error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put(
    "/admin/avatar-templates/{template_id}/roles/{role_id}",
    response_model=AvatarTemplateRoleResponse,
)
async def update_role(
    template_id: UUID,
    role_id: UUID,
    data: AvatarTemplateRoleUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return await template_service.update_role(db, template_id, role_id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"update_role error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/admin/avatar-templates/{template_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_role(
    template_id: UUID,
    role_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        await template_service.delete_role(db, template_id, role_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_role error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch(
    "/admin/avatar-templates/{template_id}/roles/reorder",
    response_model=List[AvatarTemplateRoleResponse],
)
async def reorder_roles(
    template_id: UUID,
    data: RoleReorderRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Accept an ordered list of role IDs; assigns sort_order 0, 1, 2, ..."""
    try:
        return await template_service.reorder_roles(db, template_id, data.role_ids)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"reorder_roles error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════
# Admin — template avatar image management
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/admin/avatar-templates/{template_id}/image",
    response_model=TemplateImageResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_template_image(
    template_id: UUID,
    file: UploadFile = File(...),
    current_user = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Upload or replace the avatar image for a template.
    Accepts any common image format (PNG, JPG, WEBP, SVG).
    The stored path/URL is returned as avatar_image_url.
    """
    ct = file.content_type or ""
    if not ct.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image (PNG, JPG, WEBP, SVG, etc.)")
    try:
        template = await template_service.upload_image(db, template_id, file)
        return {"id": template.id, "avatar_image_url": template.avatar_image_url}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"upload_template_image error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/admin/avatar-templates/{template_id}/image",
    response_model=TemplateImageResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_template_image(
    template_id: UUID,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Remove the avatar image from a template."""
    try:
        template = await template_service.delete_image(db, template_id)
        return {"id": template.id, "avatar_image_url": None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_template_image error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════
# Admin — template management dashboard data
# ══════════════════════════════════════════════════════════════════

@router.get(
    "/admin/avatar-templates/{template_id}/stats",
    response_model=TemplateDashboardStats,
)
async def get_template_stats(
    template_id: UUID,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Overview stats for the admin avatar management dashboard."""
    try:
        return template_service.get_stats(db, template_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_template_stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/admin/avatar-templates/{template_id}/publishers",
    response_model=List[TemplatePublisherRow],
)
async def get_template_publishers(
    template_id: UUID,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """All publishers who created avatars from this template."""
    try:
        return template_service.get_publishers(db, template_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_template_publishers error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/admin/avatar-templates/{template_id}/courses",
    response_model=List[TemplateCourseRow],
)
async def get_template_courses(
    template_id: UUID,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """All courses that use at least one avatar from this template."""
    try:
        return template_service.get_courses(db, template_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_template_courses error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/admin/avatar-templates/{template_id}/sessions",
    response_model=List[TemplateSessionRunRow],
)
async def get_template_sessions(
    template_id: UUID,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Recent session runs for sessions using avatars of this template."""
    try:
        return template_service.get_session_runs(db, template_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_template_sessions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════
# Publisher — browse active published templates + read roles
# ══════════════════════════════════════════════════════════════════

@router.get(
    "/publisher/avatar-templates",
    response_model=List[AvatarTemplateSummary],
)
async def list_active_templates_for_publisher(
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    try:
        return await template_service.list_active_templates(db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_active_templates error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/publisher/avatar-templates/{template_id}/roles",
    response_model=List[AvatarTemplateRoleResponse],
)
async def get_template_roles_for_publisher(
    template_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Publisher-visible: returns enabled roles for a published template.
    Used to populate the role selector when creating/starting a session.
    Prompt fields (prompt_context) ARE included so the frontend can inject
    them into the chat request preferences — they are never shown directly
    to subscribers.
    """
    try:
        template = await template_service.get_template(db, template_id)
        if not template or not template.is_active:
            raise HTTPException(status_code=404, detail="Template not found")
        return [r for r in template.roles if r.is_enabled]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_template_roles_for_publisher error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
