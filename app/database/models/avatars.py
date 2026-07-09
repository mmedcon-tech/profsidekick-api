import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class Avatar(Base):
    __tablename__ = "avatars"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("avatar_templates.id"), nullable=False)
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_published = Column(Boolean, default=False)
    subscription_cost = Column(Numeric(12, 6), nullable=False, default=3, server_default="3")
    template_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatar_template_versions.id", name="fk_avatars_template_version"),
        nullable=True,
    )

    # W1A addition
    allow_subscriber_variant_switch = Column(Boolean, nullable=False, default=True, server_default="true")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    template = relationship("AvatarTemplate", back_populates="avatars")
    template_version = relationship("AvatarTemplateVersion", foreign_keys=[template_version_id])
    publisher = relationship("User", back_populates="avatars_published", foreign_keys=[publisher_id])
    configuration = relationship(
        "AvatarConfiguration", back_populates="avatar", uselist=False, cascade="all, delete-orphan"
    )
    profile = relationship(
        "PublisherAvatarProfile", back_populates="avatar", uselist=False, cascade="all, delete-orphan"
    )
    sessions = relationship("Session", back_populates="avatar")
    variants = relationship("AvatarVariant", back_populates="avatar", cascade="all, delete-orphan")
    # W3 additions
    avatar_courses = relationship("AvatarCourse", back_populates="avatar", cascade="all, delete-orphan")
    access_codes = relationship("AvatarAccessCode", back_populates="avatar", cascade="all, delete-orphan")


class PublisherAvatarProfile(Base):
    """Structured teaching preferences + generated persona prompt for a publisher avatar."""
    __tablename__ = "publisher_avatar_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False, unique=True)
    teaching_pace = Column(String(50), nullable=True)
    questioning_style = Column(String(50), nullable=True)
    formality_level = Column(String(50), nullable=True)
    depth_level = Column(String(50), nullable=True)
    encouragement_level = Column(String(50), nullable=True)
    language_level = Column(String(50), nullable=True)
    refined_prompt = Column(Text, nullable=True)

    # W1A addition
    post_session_quiz_enabled = Column(Boolean, nullable=False, default=False, server_default="false")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    avatar = relationship("Avatar", back_populates="profile")


class AvatarConfiguration(Base):
    __tablename__ = "avatar_configurations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False, unique=True)
    voice = Column(String(100), nullable=True)
    language = Column(String(50), nullable=True)
    difficulty_level = Column(String(50), nullable=True)
    additional_settings = Column(JSONB, nullable=True)
    # Dual voice pipeline — publisher-default TTS provider for `voice`.
    # Nullable: legacy rows are backfilled at publish time via
    # voice_catalog_service.infer_provider_from_voice() rather than migrated.
    tts_provider = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    avatar = relationship("Avatar", back_populates="configuration")
    rubrics = relationship("Rubric", back_populates="avatar_configuration", cascade="all, delete-orphan")
    knowledge_documents = relationship(
        "KnowledgeDocument", back_populates="avatar_configuration", cascade="all, delete-orphan"
    )
    reference_solutions = relationship(
        "ReferenceSolution", back_populates="avatar_configuration", cascade="all, delete-orphan"
    )
