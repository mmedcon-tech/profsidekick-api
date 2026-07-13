"""
Prompt System API — admin template management, publisher prompt management,
and avatar prompt config management.

Route summary:
  Admin
    GET    /api/admin/prompt-templates           list all templates
    POST   /api/admin/prompt-templates           create template
    GET    /api/admin/prompt-templates/{id}      get single template
    PUT    /api/admin/prompt-templates/{id}      update template (bumps version on body change)
    DELETE /api/admin/prompt-templates/{id}      soft-delete (blocked for is_system=TRUE)

  Any authenticated user
    GET    /api/prompt-use-cases                 list valid use_case strings for dropdowns

  Publisher (system templates + own templates)
    GET    /api/publisher/prompt-templates       list system templates + publisher's own
    POST   /api/publisher/prompt-templates       create own template (is_system=False)
    PUT    /api/publisher/prompt-templates/{id}  update own template
    DELETE /api/publisher/prompt-templates/{id}  soft-delete own template

  Publisher (avatar prompt config management)
    GET    /api/avatars/{avatar_id}/prompt-configs           list configs for avatar
    PUT    /api/avatars/{avatar_id}/prompt-configs/{use_case} upsert config
    DELETE /api/avatars/{avatar_id}/prompt-configs/{use_case} remove config (revert to default)
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Avatar, User
from app.database.models.prompts import PromptTemplate
from app.dependencies.auth import get_current_user, require_admin, require_publisher
from app.schemas.schemas import (
    AvatarPromptConfigResponse,
    AvatarPromptConfigUpsert,
    PromptTemplateCreate,
    PromptTemplateResponse,
    PromptTemplateUpdate,
)
from sqlalchemy import or_
from app.services.prompt_template_service import PromptTemplateService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["prompt-templates"])

_svc = PromptTemplateService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stale(config, db: Session) -> Optional[bool]:
    """
    Return True when the admin template has been updated since the publisher
    last saved their override.  Returns None when staleness is not applicable
    (no template linked, or no override saved yet).
    """
    if config.prompt_template_id is None or config.pinned_version is None:
        return None
    template = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.id == config.prompt_template_id)
        .first()
    )
    if template is None:
        return None
    return template.version > config.pinned_version


def _config_response(config, db: Session) -> AvatarPromptConfigResponse:
    resp = AvatarPromptConfigResponse.model_validate(config)
    resp.is_stale = _stale(config, db)
    return resp


def _require_avatar_ownership(db: Session, avatar_id: UUID, publisher: User) -> Avatar:
    """Load the avatar and verify the caller owns it (or is admin)."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found.")
    if publisher.role != "admin" and avatar.publisher_id != publisher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to configure this avatar.",
        )
    return avatar


# ---------------------------------------------------------------------------
# Admin — template CRUD
# ---------------------------------------------------------------------------

@router.get(
    "/admin/prompt-templates",
    response_model=List[PromptTemplateResponse],
)
def admin_list_templates(
    use_case: Optional[str] = Query(default=None),
    active_only: bool = Query(default=False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all prompt templates. Admin sees inactive ones too by default."""
    return _svc.list_templates(db, use_case=use_case, active_only=active_only)


@router.post(
    "/admin/prompt-templates",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_template(
    body: PromptTemplateCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _svc.create_template(
        db,
        admin_id=admin.id,
        name=body.name,
        use_case=body.use_case,
        body=body.body,
        description=body.description,
    )


@router.get(
    "/admin/prompt-templates/{template_id}",
    response_model=PromptTemplateResponse,
)
def admin_get_template(
    template_id: UUID,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _svc.get_template(db, template_id)


@router.put(
    "/admin/prompt-templates/{template_id}",
    response_model=PromptTemplateResponse,
)
def admin_update_template(
    template_id: UUID,
    body: PromptTemplateUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _svc.update_template(
        db,
        template_id=template_id,
        name=body.name,
        description=body.description,
        use_case=body.use_case,
        body=body.body,
    )


@router.delete(
    "/admin/prompt-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def admin_deactivate_template(
    template_id: UUID,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Soft-delete (is_active=FALSE). Blocked for is_system=TRUE templates."""
    _svc.deactivate_template(db, template_id)


# ---------------------------------------------------------------------------
# Any authenticated user — use-case catalogue for dropdowns
# ---------------------------------------------------------------------------

@router.get("/prompt-use-cases", response_model=List[str])
def list_use_cases(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return distinct active use_case values for frontend dropdowns."""
    return _svc.list_use_cases(db)


# ---------------------------------------------------------------------------
# Publisher — own prompt templates (CRUD) + system templates (read)
# ---------------------------------------------------------------------------

@router.get(
    "/publisher/prompt-templates",
    response_model=List[PromptTemplateResponse],
)
def publisher_list_templates(
    use_case: Optional[str] = Query(default=None),
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Return active system templates (visible to all publishers) plus the
    calling publisher's own non-system templates.  Excludes other publishers'
    templates entirely.
    """
    q = db.query(PromptTemplate).filter(PromptTemplate.is_active == True)
    q = q.filter(
        or_(
            PromptTemplate.is_system == True,
            PromptTemplate.created_by == publisher.id,
        )
    )
    if use_case:
        q = q.filter(PromptTemplate.use_case == use_case)
    return q.order_by(PromptTemplate.is_system.desc(), PromptTemplate.created_at.asc()).all()


@router.post(
    "/publisher/prompt-templates",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
def publisher_create_template(
    body: PromptTemplateCreate,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """Create a non-system prompt template owned by the calling publisher."""
    return _svc.create_template(
        db,
        admin_id=publisher.id,
        name=body.name,
        use_case=body.use_case,
        body=body.body,
        description=body.description,
    )


@router.put(
    "/publisher/prompt-templates/{template_id}",
    response_model=PromptTemplateResponse,
)
def publisher_update_template(
    template_id: UUID,
    body: PromptTemplateUpdate,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """Update a prompt template the publisher owns. System templates are blocked."""
    template = _svc.get_template(db, template_id)
    if template.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System templates cannot be edited by publishers.",
        )
    if template.created_by != publisher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own prompt templates.",
        )
    return _svc.update_template(
        db,
        template_id=template_id,
        name=body.name,
        description=body.description,
        use_case=body.use_case,
        body=body.body,
    )


@router.delete(
    "/publisher/prompt-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def publisher_deactivate_template(
    template_id: UUID,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """Soft-delete a prompt template the publisher owns. System templates are blocked."""
    template = _svc.get_template(db, template_id)
    if template.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System templates cannot be deleted by publishers.",
        )
    if template.created_by != publisher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own prompt templates.",
        )
    _svc.deactivate_template(db, template_id)


# ---------------------------------------------------------------------------
# Publisher — avatar prompt config management
# ---------------------------------------------------------------------------

@router.get(
    "/avatars/{avatar_id}/prompt-configs",
    response_model=List[AvatarPromptConfigResponse],
)
def list_avatar_prompt_configs(
    avatar_id: UUID,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    _require_avatar_ownership(db, avatar_id, publisher)
    configs = _svc.list_avatar_configs(db, avatar_id)
    return [_config_response(c, db) for c in configs]


@router.put(
    "/avatars/{avatar_id}/prompt-configs/{use_case}",
    response_model=AvatarPromptConfigResponse,
)
def upsert_avatar_prompt_config(
    avatar_id: UUID,
    use_case: str,
    body: AvatarPromptConfigUpsert,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Create or replace the avatar's prompt configuration for this use_case.
    The UNIQUE(avatar_id, use_case) constraint means this is always an upsert.
    """
    _require_avatar_ownership(db, avatar_id, publisher)
    config = _svc.upsert_avatar_config(
        db,
        avatar_id=avatar_id,
        use_case=use_case,
        prompt_template_id=body.prompt_template_id,
        is_enabled=body.is_enabled,
        override_body=body.override_body,
        override_name=body.override_name,
        is_custom=body.is_custom,
    )
    return _config_response(config, db)


@router.delete(
    "/avatars/{avatar_id}/prompt-configs/{use_case}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_avatar_prompt_config(
    avatar_id: UUID,
    use_case: str,
    publisher: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """Remove the config for this use_case, reverting the avatar to the system default."""
    _require_avatar_ownership(db, avatar_id, publisher)
    _svc.delete_avatar_config(db, avatar_id, use_case)
