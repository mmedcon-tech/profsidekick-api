from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database.models.prompts import AvatarPromptConfig, PromptTemplate


class PromptTemplateService:
    """
    Admin-facing CRUD for the global prompt template registry.

    Rules enforced here (not at the DB level):
      - is_system=TRUE templates may not be deleted or deactivated.
      - Editing the body of any template bumps its `version` counter so that
        AvatarPromptConfig.pinned_version comparisons detect staleness.
      - Callers must verify the requester has admin role before calling mutating
        methods — this service trusts the API layer for auth.
    """

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_templates(
        self,
        db: Session,
        use_case: Optional[str] = None,
        active_only: bool = True,
    ) -> List[PromptTemplate]:
        q = db.query(PromptTemplate)
        if active_only:
            q = q.filter(PromptTemplate.is_active == True)
        if use_case:
            q = q.filter(PromptTemplate.use_case == use_case)
        return q.order_by(PromptTemplate.is_system.desc(), PromptTemplate.created_at.asc()).all()

    def get_template(self, db: Session, template_id: UUID) -> PromptTemplate:
        template = (
            db.query(PromptTemplate)
            .filter(PromptTemplate.id == template_id)
            .first()
        )
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prompt template not found.",
            )
        return template

    def list_use_cases(self, db: Session) -> List[str]:
        """Return distinct active use_case values — used to populate dropdowns."""
        rows = (
            db.query(PromptTemplate.use_case)
            .filter(PromptTemplate.is_active == True)
            .distinct()
            .order_by(PromptTemplate.use_case)
            .all()
        )
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Writes (admin only)
    # ------------------------------------------------------------------

    def create_template(
        self,
        db: Session,
        admin_id: UUID,
        name: str,
        use_case: str,
        body: str,
        description: Optional[str] = None,
    ) -> PromptTemplate:
        template = PromptTemplate(
            id=uuid.uuid4(),
            name=name,
            description=description,
            use_case=use_case,
            body=body,
            is_system=False,
            is_active=True,
            version=1,
            created_by=admin_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        return template

    def update_template(
        self,
        db: Session,
        template_id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        use_case: Optional[str] = None,
        body: Optional[str] = None,
    ) -> PromptTemplate:
        template = self.get_template(db, template_id)

        body_changed = body is not None and body != template.body

        if name is not None:
            template.name = name
        if description is not None:
            template.description = description
        if use_case is not None:
            template.use_case = use_case
        if body is not None:
            template.body = body

        if body_changed:
            template.version += 1

        template.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(template)
        return template

    def deactivate_template(self, db: Session, template_id: UUID) -> PromptTemplate:
        """
        Soft-delete: set is_active=FALSE.
        Blocked for is_system=TRUE templates — they must always exist as fallbacks.
        """
        template = self.get_template(db, template_id)
        if template.is_system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System prompt templates cannot be deleted or deactivated.",
            )
        template.is_active = False
        template.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(template)
        return template

    # ------------------------------------------------------------------
    # Avatar prompt config management (publisher-facing, called by avatar API)
    # ------------------------------------------------------------------

    def list_avatar_configs(
        self, db: Session, avatar_id: UUID
    ) -> List[AvatarPromptConfig]:
        return (
            db.query(AvatarPromptConfig)
            .filter(AvatarPromptConfig.avatar_id == avatar_id)
            .order_by(AvatarPromptConfig.use_case)
            .all()
        )

    def upsert_avatar_config(
        self,
        db: Session,
        avatar_id: UUID,
        use_case: str,
        prompt_template_id: Optional[UUID],
        is_enabled: bool,
        override_body: Optional[str],
        override_name: Optional[str],
        is_custom: bool,
    ) -> AvatarPromptConfig:
        """
        Create or replace the avatar's config for this use_case.
        When override_body is set and a prompt_template_id is also provided,
        pinned_version is captured from the current template version so the
        frontend can show a staleness warning if the admin later edits the template.
        """
        pinned_version: Optional[int] = None
        if override_body and prompt_template_id:
            template = (
                db.query(PromptTemplate)
                .filter(PromptTemplate.id == prompt_template_id)
                .first()
            )
            if template:
                pinned_version = template.version

        config = (
            db.query(AvatarPromptConfig)
            .filter(
                AvatarPromptConfig.avatar_id == avatar_id,
                AvatarPromptConfig.use_case == use_case,
            )
            .first()
        )

        now = datetime.utcnow()

        if config is None:
            config = AvatarPromptConfig(
                id=uuid.uuid4(),
                avatar_id=avatar_id,
                use_case=use_case,
                created_at=now,
            )
            db.add(config)

        config.prompt_template_id = prompt_template_id
        config.is_enabled = is_enabled
        config.override_body = override_body
        config.override_name = override_name
        config.is_custom = is_custom
        config.pinned_version = pinned_version
        config.updated_at = now

        db.commit()
        db.refresh(config)
        return config

    def delete_avatar_config(
        self, db: Session, avatar_id: UUID, use_case: str
    ) -> None:
        """Remove the avatar's config for this use_case, reverting to system default."""
        config = (
            db.query(AvatarPromptConfig)
            .filter(
                AvatarPromptConfig.avatar_id == avatar_id,
                AvatarPromptConfig.use_case == use_case,
            )
            .first()
        )
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No prompt config found for use_case '{use_case}' on this avatar.",
            )
        db.delete(config)
        db.commit()
