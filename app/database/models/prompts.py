import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class PromptTemplate(Base):
    """
    Admin-managed global prompt template registry.

    is_system=TRUE rows are the four built-in defaults seeded at migration time.
    The API layer blocks deletion of system templates; edits are allowed and
    bump `version` so AvatarPromptConfig.pinned_version can detect staleness.

    use_case is a free-form string (not a DB enum) so new categories can be
    added by inserting a row, not by altering the schema.  Well-known values:
        session.teaching   session.examination   session.conversation
        grading.assessment
    """
    __tablename__ = "prompt_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    use_case = Column(String(100), nullable=False)
    body = Column(Text, nullable=False)
    is_system = Column(Boolean, nullable=False, default=False, server_default="false")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    version = Column(Integer, nullable=False, default=1, server_default="1")
    # NULL for system-seeded templates — no individual admin "owns" them.
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by])
    # No cascade here — deleting a PromptTemplate sets prompt_template_id NULL
    # on linked AvatarPromptConfig rows (DB-level ON DELETE SET NULL).
    # The config rows themselves survive; runtime falls through to system default.
    prompt_configs = relationship(
        "AvatarPromptConfig",
        back_populates="prompt_template",
        passive_deletes=True,
    )


class AvatarPromptConfig(Base):
    """
    Per-avatar prompt configuration created by a publisher.

    Links an avatar to a PromptTemplate for a specific use_case, with an
    optional override of the template body.  The UNIQUE(avatar_id, use_case)
    constraint (enforced by the DB) ensures one active config per use-case.

    Resolution priority (applied in PromptResolutionService):
      1. override_body (if not NULL)      — publisher-customised text
      2. PromptTemplate.body              — admin template text as-is
      3. system default PromptTemplate    — fallback when no config exists
      4. legacy AvatarTemplateVersion     — ultimate fallback during migration

    Scenarios:

      Admin template, no edit  → prompt_template_id SET, override_body NULL,  is_custom FALSE
      Admin template + edit    → prompt_template_id SET, override_body SET,    is_custom FALSE
      Publisher-created        → prompt_template_id NULL, override_body SET,   is_custom TRUE
    """
    __tablename__ = "avatar_prompt_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatars.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SET NULL so the config row survives if the admin template is deleted.
    prompt_template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    use_case = Column(String(100), nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    # NULL = no override; use the admin template body as-is.
    override_body = Column(Text, nullable=True)
    # Display label used in the UI for publisher-created (is_custom=TRUE) prompts.
    override_name = Column(Text, nullable=True)
    # Admin template version at the time the publisher last saved an override.
    # If PromptTemplate.version > pinned_version the frontend shows a staleness warning.
    pinned_version = Column(Integer, nullable=True)
    is_custom = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    avatar = relationship("Avatar", back_populates="prompt_configs")
    prompt_template = relationship("PromptTemplate", back_populates="prompt_configs")
