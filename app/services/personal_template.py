"""
Built-in "Personal avatar" template.

Avatar creation requires an active template with a published version, and a
fresh database has none, so a new creator could not make an avatar without an
admin. This template fills that gap. Its category ("General") resolves to the
general profession profile, and its version leaves the mode prompts empty so
the general profile's neutral base prompt is used (see profession_profiles).

ensure_personal_template() is idempotent. If the template already exists it is
returned unchanged, so an admin who edits or deactivates it keeps that choice.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.database.models import AvatarTemplate, AvatarTemplateVersion
from app.services.audit_service import record_audit_event

# Fixed so the frontend wizard can preselect it (src/lib/personalTemplate.ts).
PERSONAL_TEMPLATE_ID = uuid.UUID("5e7b9a1c-2d4f-4c6e-8a0b-9c1d2e3f4a5b")
PERSONAL_TEMPLATE_VERSION_ID = uuid.UUID("5e7b9a1c-2d4f-4c6e-8a0b-9c1d2e3f4a5c")
PERSONAL_TEMPLATE_CATEGORY = "General"


def ensure_personal_template(db: Session, admin_id) -> AvatarTemplate:
    existing = (
        db.query(AvatarTemplate)
        .filter(AvatarTemplate.id == PERSONAL_TEMPLATE_ID)
        .first()
    )
    if existing:
        return existing

    now = datetime.utcnow()
    template = AvatarTemplate(
        id=PERSONAL_TEMPLATE_ID,
        created_by=admin_id,
        name="Personal avatar",
        description=(
            "An AI avatar of you. It answers from what you add "
            "and in the style you choose. Works for any field."
        ),
        category=PERSONAL_TEMPLATE_CATEGORY,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(template)
    db.flush()

    version = AvatarTemplateVersion(
        id=PERSONAL_TEMPLATE_VERSION_ID,
        template_id=template.id,
        version_number=1,
        # Empty on purpose: the general profession profile supplies the prompt.
        conversation_prompt=None,
        teaching_prompt=None,
        examination_prompt=None,
        document_analysis_prompt=None,
        status="published",
        change_notes="Built-in template seeded by ensure_personal_template().",
        created_by=admin_id,
        created_at=now,
        published_at=now,
        published_by=admin_id,
    )
    db.add(version)
    db.flush()
    template.current_version_id = version.id

    record_audit_event(
        db,
        action="avatar_template.seeded",
        entity_type="avatar_template",
        entity_id=template.id,
        actor_user_id=admin_id,
        data={"name": template.name, "category": template.category},
    )
    db.commit()
    db.refresh(template)
    return template
