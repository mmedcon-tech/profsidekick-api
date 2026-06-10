import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, distinct
from fastapi import HTTPException, status, UploadFile
from app.config import settings
from app.database.models import (
    AvatarTemplate, AvatarTemplateVersion, AvatarTemplateRole,
    Avatar, Session as SessionModel, SessionRun, Course, User,
)
from app.schemas.schemas import (
    AvatarTemplateCreate,
    AvatarTemplateUpdate,
    AvatarTemplateVersionCreate,
    AvatarTemplateRoleCreate,
    AvatarTemplateRoleUpdate,
)


def _published_state(template: AvatarTemplate) -> str:
    """Derive published_state string from versions list."""
    if not template.versions:
        return "unpublished"
    statuses = {v.status for v in template.versions}
    if "published" in statuses:
        return "published"
    if "draft" in statuses:
        return "draft"
    return "archived"


def _enrich(template: AvatarTemplate) -> AvatarTemplate:
    """Attach computed attributes used by response schemas."""
    template.published_state = _published_state(template)
    template.version_count = len(template.versions)
    # avatar_image_url mirrors avatar_image_path (path IS the URL or relative path)
    template.avatar_image_url = template.avatar_image_path or None
    return template


async def _save_template_image(file: UploadFile, template_id) -> str:
    """
    Save an uploaded image file for a template.
    Returns the stored path/URL for avatar_image_path.
    Supports cloud storage (S3) or local static directory.
    """
    content = await file.read()
    ext = Path(file.filename or "image.png").suffix.lower() or ".png"
    filename = f"avatar_{uuid.uuid4().hex}{ext}"

    if settings.use_cloud_storage:
        from app.services.cloud_storage_service import cloud_storage
        key = f"template_images/{template_id}/{filename}"
        url = await cloud_storage.upload_image(content, key, file.content_type or "image/png")
        return url
    else:
        # Local static storage
        img_dir = Path(settings.static_dir) / "template_images" / str(template_id)
        img_dir.mkdir(parents=True, exist_ok=True)
        img_path = img_dir / filename
        with open(img_path, "wb") as f:
            f.write(content)
        return f"/static/template_images/{template_id}/{filename}"


class AvatarTemplateService:
    """Admin-only service. All prompt fields are managed through versions."""

    def _load(self, db: Session, template_id) -> Optional[AvatarTemplate]:
        return (
            db.query(AvatarTemplate)
            .options(
                joinedload(AvatarTemplate.versions),
                joinedload(AvatarTemplate.roles),
                joinedload(AvatarTemplate.current_version),
            )
            .filter(AvatarTemplate.id == template_id)
            .first()
        )

    async def create_template(
        self,
        db: Session,
        admin_id,
        data: AvatarTemplateCreate,
    ) -> AvatarTemplate:
        template = AvatarTemplate(
            id=uuid.uuid4(),
            created_by=admin_id,
            name=data.name,
            description=data.description,
            category=data.category,
            is_active=True,
            subscription_cost=data.subscription_cost if data.subscription_cost is not None else 3,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        return _enrich(self._load(db, template.id))

    async def get_template(self, db: Session, template_id) -> Optional[AvatarTemplate]:
        t = self._load(db, template_id)
        if t:
            _enrich(t)
        return t

    async def list_templates(self, db: Session) -> List[AvatarTemplate]:
        templates = (
            db.query(AvatarTemplate)
            .options(
                joinedload(AvatarTemplate.versions),
                joinedload(AvatarTemplate.roles),
                joinedload(AvatarTemplate.current_version),
            )
            .order_by(AvatarTemplate.created_at.desc())
            .all()
        )
        for t in templates:
            _enrich(t)
        return templates

    async def list_active_templates(self, db: Session) -> List[AvatarTemplate]:
        """Active templates with a published version — safe for publisher browsing."""
        templates = (
            db.query(AvatarTemplate)
            .options(joinedload(AvatarTemplate.versions))
            .filter(AvatarTemplate.is_active == True)
            .order_by(AvatarTemplate.created_at.desc())
            .all()
        )
        result = []
        for t in templates:
            _enrich(t)
            if t.published_state == "published":
                result.append(t)
        return result

    async def update_template(
        self,
        db: Session,
        template_id,
        data: AvatarTemplateUpdate,
    ) -> AvatarTemplate:
        template = self._load(db, template_id)
        if not template:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

        if data.name is not None:
            template.name = data.name
        if data.description is not None:
            template.description = data.description
        if data.category is not None:
            template.category = data.category
        if data.is_active is not None:
            template.is_active = data.is_active

        template.updated_at = datetime.utcnow()
        db.commit()
        return _enrich(self._load(db, template_id))

    async def archive_template(self, db: Session, template_id) -> AvatarTemplate:
        """Soft-delete: sets is_active=False. Does not cascade to avatars."""
        template = self._load(db, template_id)
        if not template:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

        template.is_active = False
        template.updated_at = datetime.utcnow()
        db.commit()
        return _enrich(self._load(db, template_id))

    # ── Version management ────────────────────────────────────────────

    async def save_draft(
        self,
        db: Session,
        template_id,
        data: AvatarTemplateVersionCreate,
        admin_id,
    ) -> AvatarTemplateVersion:
        template = self._load(db, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        next_number = (
            max((v.version_number for v in template.versions), default=0) + 1
        )
        version = AvatarTemplateVersion(
            id=uuid.uuid4(),
            template_id=template.id,
            version_number=next_number,
            conversation_prompt=data.conversation_prompt,
            teaching_prompt=data.teaching_prompt,
            examination_prompt=data.examination_prompt,
            document_analysis_prompt=data.document_analysis_prompt,
            change_notes=data.change_notes,
            status="draft",
            created_by=admin_id,
            created_at=datetime.utcnow(),
        )
        db.add(version)
        db.commit()
        db.refresh(version)
        return version

    async def publish_version(
        self,
        db: Session,
        template_id,
        version_id,
        admin_id,
    ) -> AvatarTemplateVersion:
        template = self._load(db, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        version = next((v for v in template.versions if str(v.id) == str(version_id)), None)
        if not version:
            raise HTTPException(status_code=404, detail="Version not found")
        if version.status == "published":
            raise HTTPException(status_code=409, detail="Version is already published")

        # Archive previous published version
        for v in template.versions:
            if v.status == "published":
                v.status = "archived"

        version.status = "published"
        version.published_at = datetime.utcnow()
        version.published_by = admin_id

        # Point template to new current version
        template.current_version_id = version.id
        template.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(version)
        return version

    async def list_versions(
        self, db: Session, template_id
    ) -> List[AvatarTemplateVersion]:
        template = self._load(db, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        return sorted(template.versions, key=lambda v: v.version_number, reverse=True)

    # ── Image management ─────────────────────────────────────────────

    async def upload_image(self, db: Session, template_id, file: UploadFile) -> AvatarTemplate:
        template = self._load(db, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # Delete old local file if present
        old_path = template.avatar_image_path or ""
        if old_path.startswith("/static/") and not old_path.startswith("http"):
            local_path = Path(settings.static_dir) / old_path.lstrip("/static/")
            if local_path.exists():
                local_path.unlink(missing_ok=True)

        path = await _save_template_image(file, template_id)
        template.avatar_image_path = path
        template.updated_at = datetime.utcnow()
        db.commit()
        return _enrich(self._load(db, template_id))

    async def delete_image(self, db: Session, template_id) -> AvatarTemplate:
        template = self._load(db, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        old_path = template.avatar_image_path or ""
        if old_path.startswith("/static/") and not old_path.startswith("http"):
            local_path = Path(settings.static_dir) / old_path.lstrip("/static/")
            if local_path.exists():
                local_path.unlink(missing_ok=True)

        template.avatar_image_path = None
        template.updated_at = datetime.utcnow()
        db.commit()
        return _enrich(self._load(db, template_id))

    # ── Dashboard stats ───────────────────────────────────────────────

    def get_stats(self, db: Session, template_id) -> dict:
        """Aggregate stats for the admin dashboard overview panel."""
        template = self._load(db, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        _enrich(template)

        publisher_count = (
            db.query(func.count(distinct(Avatar.publisher_id)))
            .filter(Avatar.template_id == template_id)
            .scalar() or 0
        )
        avatar_ids = (
            db.query(Avatar.id)
            .filter(Avatar.template_id == template_id)
            .subquery()
        )
        session_q = (
            db.query(SessionModel)
            .filter(SessionModel.avatar_id.in_(avatar_ids))
        )
        session_count = session_q.count()
        session_ids = db.query(SessionModel.id).filter(SessionModel.avatar_id.in_(avatar_ids)).subquery()
        course_count = (
            db.query(func.count(distinct(SessionModel.course_id)))
            .filter(SessionModel.avatar_id.in_(avatar_ids))
            .scalar() or 0
        )
        session_run_count = (
            db.query(func.count(SessionRun.id))
            .filter(SessionRun.session_id.in_(session_ids))
            .scalar() or 0
        )

        return {
            "template_id": template.id,
            "name": template.name,
            "avatar_image_url": template.avatar_image_url,
            "published_state": template.published_state,
            "version_count": template.version_count,
            "publisher_count": publisher_count,
            "course_count": course_count,
            "session_count": session_count,
            "session_run_count": session_run_count,
        }

    def get_publishers(self, db: Session, template_id) -> list:
        """Publishers who created at least one avatar from this template."""
        rows = (
            db.query(Avatar, User)
            .join(User, User.id == Avatar.publisher_id)
            .filter(Avatar.template_id == template_id)
            .order_by(Avatar.created_at.desc())
            .all()
        )
        return [
            {
                "publisher_id": user.id,
                "username": user.username,
                "email": user.email,
                "avatar_id": avatar.id,
                "avatar_name": avatar.name,
                "is_published": avatar.is_published,
                "created_at": avatar.created_at,
            }
            for avatar, user in rows
        ]

    def get_courses(self, db: Session, template_id) -> list:
        """Distinct courses that have at least one session using an avatar of this template."""
        avatar_ids = (
            db.query(Avatar.id)
            .filter(Avatar.template_id == template_id)
            .subquery()
        )
        rows = (
            db.query(Course, User, func.count(SessionModel.id).label("session_count"))
            .join(SessionModel, SessionModel.course_id == Course.id)
            .join(User, User.id == Course.user_id)
            .filter(SessionModel.avatar_id.in_(avatar_ids))
            .group_by(Course.id, User.id)
            .order_by(func.count(SessionModel.id).desc())
            .all()
        )
        return [
            {
                "course_id": course.course_id,
                "name": course.name,
                "code": course.code,
                "publisher_username": user.username,
                "session_count": session_count,
                "is_active": course.is_active,
            }
            for course, user, session_count in rows
        ]

    def get_session_runs(self, db: Session, template_id, limit: int = 100) -> list:
        """Recent session runs for sessions using avatars of this template."""
        avatar_ids = (
            db.query(Avatar.id)
            .filter(Avatar.template_id == template_id)
            .subquery()
        )
        session_ids = (
            db.query(SessionModel.id, SessionModel.session_id, SessionModel.class_name)
            .filter(SessionModel.avatar_id.in_(avatar_ids))
            .subquery()
        )
        rows = (
            db.query(SessionRun, User, session_ids.c.session_id, session_ids.c.class_name)
            .join(User, User.id == SessionRun.user_id)
            .join(session_ids, session_ids.c.id == SessionRun.session_id)
            .order_by(SessionRun.start_time.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "run_id": run.id,
                "session_id": sess_id,
                "session_name": class_name,
                "publisher_username": user.username,
                "status": run.status.value if hasattr(run.status, "value") else str(run.status),
                "start_time": run.start_time,
                "end_time": run.end_time,
                "role_at_start": run.role_at_start,
            }
            for run, user, sess_id, class_name in rows
        ]

    # ── Role management ───────────────────────────────────────────────

    async def create_role(
        self,
        db: Session,
        template_id,
        data: AvatarTemplateRoleCreate,
        admin_id,
    ) -> AvatarTemplateRole:
        template = self._load(db, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        max_order = max((r.sort_order for r in template.roles), default=-1)
        role = AvatarTemplateRole(
            id=uuid.uuid4(),
            template_id=template.id,
            name=data.name,
            description=data.description,
            prompt_context=data.prompt_context,
            is_enabled=True,
            sort_order=max_order + 1,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(role)
        db.commit()
        db.refresh(role)
        return role

    async def update_role(
        self,
        db: Session,
        template_id,
        role_id,
        data: AvatarTemplateRoleUpdate,
    ) -> AvatarTemplateRole:
        role = (
            db.query(AvatarTemplateRole)
            .filter(
                AvatarTemplateRole.id == role_id,
                AvatarTemplateRole.template_id == template_id,
            )
            .first()
        )
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        if data.name is not None:
            role.name = data.name
        if data.description is not None:
            role.description = data.description
        if data.prompt_context is not None:
            role.prompt_context = data.prompt_context
        if data.is_enabled is not None:
            role.is_enabled = data.is_enabled
        if data.sort_order is not None:
            role.sort_order = data.sort_order

        role.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(role)
        return role

    async def delete_role(self, db: Session, template_id, role_id) -> None:
        role = (
            db.query(AvatarTemplateRole)
            .filter(
                AvatarTemplateRole.id == role_id,
                AvatarTemplateRole.template_id == template_id,
            )
            .first()
        )
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        db.delete(role)
        db.commit()

    async def reorder_roles(
        self,
        db: Session,
        template_id,
        role_ids: List,
    ) -> List[AvatarTemplateRole]:
        template = self._load(db, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        id_strs = [str(r) for r in role_ids]
        role_map = {str(r.id): r for r in template.roles}

        for idx, rid in enumerate(id_strs):
            if rid not in role_map:
                raise HTTPException(status_code=400, detail=f"Role {rid} not found in template")
            role_map[rid].sort_order = idx
            role_map[rid].updated_at = datetime.utcnow()

        db.commit()
        return sorted(template.roles, key=lambda r: r.sort_order)
