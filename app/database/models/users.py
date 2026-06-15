import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class UserAgreement(Base):
    """W2C: Audit log of a user accepting a legal agreement."""
    __tablename__ = "user_agreements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agreement_type = Column(String(50), nullable=False)
    agreed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    user = relationship("User", back_populates="agreements")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    role = Column(String(50), default="subscriber", nullable=False)

    # Email verification
    email_verified = Column(Boolean, nullable=True, default=False)
    email_verification_token = Column(String(255), nullable=True)
    email_verification_sent_at = Column(DateTime, nullable=True)

    # Professor approval
    is_approved = Column(Boolean, nullable=True, default=False)
    approval_token = Column(String(255), nullable=True)
    approval_request_sent_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(255), nullable=True)

    # v2 GDPR / account lifecycle (W1A additions — nullable, backfilled by migration)
    terms_accepted_at = Column(DateTime, nullable=True)
    privacy_accepted_at = Column(DateTime, nullable=True)
    gdpr_consent_at = Column(DateTime, nullable=True)
    marketing_emails_opt_in = Column(Boolean, nullable=False, default=False, server_default="false")
    is_deleted = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_at = Column(DateTime, nullable=True)

    # W2B addition — active program context for this user
    current_program_id = Column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    session_runs = relationship("SessionRun", back_populates="user", cascade="all, delete-orphan")
    prompts = relationship("SavedPrompt", back_populates="user", cascade="all, delete-orphan")
    courses_created = relationship("Course", back_populates="user", cascade="all, delete-orphan")
    courses_enrolled = relationship("Course", secondary="course_students", back_populates="students")
    avatar_templates_created = relationship(
        "AvatarTemplate", back_populates="creator", foreign_keys="[AvatarTemplate.created_by]"
    )
    avatars_published = relationship(
        "Avatar", back_populates="publisher", foreign_keys="[Avatar.publisher_id]"
    )
    agreements = relationship("UserAgreement", back_populates="user", cascade="all, delete-orphan")
    current_program = relationship("Program", foreign_keys=[current_program_id])
