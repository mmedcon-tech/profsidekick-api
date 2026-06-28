import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class AvatarTemplate(Base):
    __tablename__ = "avatar_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)
    avatar_image_path = Column(String(500), nullable=True)
    hidden_system_prompt = Column(Text, nullable=True)
    default_realtime_prompt = Column(Text, nullable=True)
    default_vision_prompt = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    subscription_cost = Column(Numeric(12, 6), nullable=False, default=3, server_default="3")
    current_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "avatar_template_versions.id",
            use_alter=True,
            name="fk_avatar_templates_current_version",
        ),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User", back_populates="avatar_templates_created", foreign_keys=[created_by])
    avatars = relationship("Avatar", back_populates="template", cascade="all, delete-orphan")
    versions = relationship(
        "AvatarTemplateVersion",
        back_populates="template",
        primaryjoin="AvatarTemplate.id == AvatarTemplateVersion.template_id",
        cascade="all, delete-orphan",
        order_by="AvatarTemplateVersion.version_number",
    )
    roles = relationship(
        "AvatarTemplateRole",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="AvatarTemplateRole.sort_order",
    )
    current_version = relationship(
        "AvatarTemplateVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )


class AvatarTemplateVersion(Base):
    """
    Immutable prompt snapshot for a template.
    Each Save Draft or Publish creates a new row — existing rows are never
    overwritten so publisher avatars remain frozen at the version they
    were created from (Option A).
    status: draft | published | archived
    """
    __tablename__ = "avatar_template_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("avatar_templates.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(Integer, nullable=False)
    conversation_prompt = Column(Text, nullable=True)
    teaching_prompt = Column(Text, nullable=True)
    examination_prompt = Column(Text, nullable=True)
    document_analysis_prompt = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    change_notes = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)
    published_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    template = relationship(
        "AvatarTemplate",
        back_populates="versions",
        foreign_keys=[template_id],
    )
    creator = relationship("User", foreign_keys=[created_by])
    publisher_user = relationship("User", foreign_keys=[published_by])


class AvatarTemplateRole(Base):
    __tablename__ = "avatar_template_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("avatar_templates.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    prompt_context = Column(Text, nullable=True)
    is_enabled = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    # W2A additions — HeyGen overrides and suggested 3-D model for this role
    heygen_avatar_id = Column(String(200), nullable=True)
    heygen_voice_id = Column(String(200), nullable=True)
    default_language = Column(String(50), nullable=True)
    suggested_3d_model_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatar_3d_models.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    template = relationship("AvatarTemplate", back_populates="roles")
    suggested_3d_model = relationship("Avatar3DModel", foreign_keys=[suggested_3d_model_id])
