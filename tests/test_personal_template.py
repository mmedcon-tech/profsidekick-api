"""
Built-in Personal avatar template (Stage A, P3).
Integration test: needs the test database (see tests/conftest.py).
"""

from __future__ import annotations

import asyncio
import uuid

from app.database.models import AuditEvent, AvatarTemplate, AvatarTemplateVersion, User
from app.schemas.schemas import AvatarCreate
from app.services.avatar_service import AvatarService
from app.services.avatar_template_service import AvatarTemplateService
from app.services.personal_template import (
    PERSONAL_TEMPLATE_ID,
    ensure_personal_template,
)
from app.services.profession_profiles import resolve_avatar_profession


def _user(db, role):
    user = User(
        id=uuid.uuid4(),
        username=f"u_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed",
        first_name="T",
        last_name="U",
        role=role,
    )
    db.add(user)
    db.commit()
    return user


def test_seed_is_idempotent_and_publishes_one_version(db_session):
    admin = _user(db_session, "admin")

    first = ensure_personal_template(db_session, admin.id)
    second = ensure_personal_template(db_session, admin.id)

    assert first.id == second.id == PERSONAL_TEMPLATE_ID
    assert (
        db_session.query(AvatarTemplate).filter_by(id=PERSONAL_TEMPLATE_ID).count() == 1
    )
    versions = (
        db_session.query(AvatarTemplateVersion)
        .filter_by(template_id=PERSONAL_TEMPLATE_ID)
        .all()
    )
    assert [v.status for v in versions] == ["published"]
    assert first.current_version_id == versions[0].id
    assert (
        db_session.query(AuditEvent)
        .filter_by(action="avatar_template.seeded", entity_id=str(PERSONAL_TEMPLATE_ID))
        .count()
        == 1
    )


def test_a_new_creator_can_create_a_general_avatar_with_no_admin_action(db_session):
    admin = _user(db_session, "admin")
    ensure_personal_template(db_session, admin.id)
    creator = _user(db_session, "publisher")

    published = asyncio.run(AvatarTemplateService().list_active_templates(db_session))
    assert PERSONAL_TEMPLATE_ID in [t.id for t in published]

    avatar = asyncio.run(
        AvatarService().create_avatar(
            db_session,
            creator.id,
            AvatarCreate(template_id=PERSONAL_TEMPLATE_ID, name="My avatar"),
        )
    )
    assert (
        avatar.template_version_id
        == db_session.get(AvatarTemplate, PERSONAL_TEMPLATE_ID).current_version_id
    )
    assert resolve_avatar_profession(avatar) == "general"
