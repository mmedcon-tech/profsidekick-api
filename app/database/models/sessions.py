import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base
from app.database.models.enums import SessionRunStatus


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(50), unique=True, nullable=False, index=True)
    session_number = Column(Integer, nullable=True)
    session_date = Column(DateTime, nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    class_name = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    duration = Column(Integer, nullable=True)
    presentation_details = Column(JSONB, nullable=True)
    slides_details = Column(JSONB, nullable=True)
    assistant_parameters = Column(JSONB, nullable=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=True)
    selected_role_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "avatar_template_roles.id",
            use_alter=True,
            name="fk_sessions_selected_role",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    role_label = Column(String(100), nullable=True)
    session_mode = Column(String(20), nullable=False, default="teaching", server_default="teaching")
    subscriber_runtime_mode = Column(String(20), nullable=False, default="avatar", server_default="avatar")

    # W1A additions
    is_published = Column(Boolean, nullable=False, default=False, server_default="false")
    title = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    session_runs = relationship("SessionRun", back_populates="session", cascade="all, delete-orphan")
    user = relationship("User", back_populates="sessions")
    course = relationship("Course", back_populates="sessions")
    session_materials = relationship("SessionMaterial", back_populates="session", cascade="all, delete-orphan")
    avatar = relationship("Avatar", back_populates="sessions")
    selected_role = relationship("AvatarTemplateRole", foreign_keys=[selected_role_id])


class SessionRun(Base):
    __tablename__ = "session_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_run_id = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    session_run_metadata = Column(JSONB)
    assistant_parameters = Column(JSONB)
    status = Column(SQLEnum(SessionRunStatus), default=SessionRunStatus.ACTIVE)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    ai_summary = Column(Text, nullable=True)
    role_at_start = Column(String(100), nullable=True)
    runtime_mode_used = Column(String(20), nullable=True)

    # W1A addition
    ai_provider = Column(String(50), nullable=False, default="openai", server_default="openai")

    # W2A additions — variant at session start
    avatar_variant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatar_variants.id", ondelete="SET NULL"),
        nullable=True,
    )
    variant_snapshot = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="session_runs")
    user = relationship("User", back_populates="session_runs")
    avatar_variant = relationship("AvatarVariant", foreign_keys=[avatar_variant_id])


class SessionMaterial(Base):
    __tablename__ = "session_materials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    course_material_id = Column(UUID(as_uuid=True), ForeignKey("course_materials.id"), nullable=False)
    is_included = Column(Boolean, default=True)
    usage_instructions = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="session_materials")
    course_material = relationship("CourseMaterial", back_populates="session_materials")
