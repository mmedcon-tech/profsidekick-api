"""
Self Assessment Exam (SAE) system models.
Completely isolated from the Math Placement Exam autograder.
Three tables: sae_students → sae_invitation_tokens → sae_submissions
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy import UniqueConstraint

from app.database.connection import Base


class SAEStudent(Base):
    """
    A pre-created student slot managed by a publisher before the exam.
    user_id is NULL until the student activates their account via the
    one-time invitation link.
    """
    __tablename__ = "sae_students"
    __table_args__ = (
        UniqueConstraint("publisher_id", "student_number",
                         name="uq_sae_student_publisher_number"),
    )

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_number = Column(Integer, nullable=False)
    student_code   = Column(String(20), unique=True, nullable=False, index=True)
    display_name   = Column(String(100), nullable=False)
    publisher_id   = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
                            nullable=False, index=True)
    user_id        = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
                            nullable=True, index=True)
    is_activated   = Column(Boolean, nullable=False, default=False)
    activated_at   = Column(DateTime, nullable=True)
    has_submitted  = Column(Boolean, nullable=False, default=False)
    submitted_at   = Column(DateTime, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)

    publisher   = relationship("User", foreign_keys=[publisher_id])
    user        = relationship("User", foreign_keys=[user_id])
    invitation  = relationship("SAEInvitationToken", back_populates="student",
                               uselist=False, cascade="all, delete-orphan")
    submission  = relationship("SAESubmission", back_populates="student",
                               uselist=False, cascade="all, delete-orphan")


class SAEInvitationToken(Base):
    """
    One-time setup link for an SAE student.
    token is a secrets.token_urlsafe(32) value (43 chars, 256-bit entropy).
    is_used is flipped to True atomically with User creation inside a transaction.
    No email is ever sent — the publisher copies the URL and distributes it offline.
    """
    __tablename__ = "sae_invitation_tokens"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True),
                        ForeignKey("sae_students.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    token      = Column(String(64), unique=True, nullable=False, index=True)
    is_used    = Column(Boolean, nullable=False, default=False)
    used_at    = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("SAEStudent", back_populates="invitation")


class SAESubmission(Base):
    """
    A single exam submission for an SAE student.
    UNIQUE(student_id) at the DB level enforces the one-submission rule.
    submitted_by_publisher=True means the publisher uploaded on behalf of the student.
    """
    __tablename__ = "sae_submissions"

    id                     = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id             = Column(UUID(as_uuid=True), ForeignKey("sae_students.id",
                                    ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    submitted_by_publisher = Column(Boolean, nullable=False, default=False)
    publisher_user_id      = Column(UUID(as_uuid=True),
                                    ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    handwritten_filename   = Column(String(255), nullable=True)
    handwritten_file_path  = Column(String(500), nullable=True)
    webassign_filename     = Column(String(255), nullable=True)
    webassign_file_path    = Column(String(500), nullable=True)
    score                  = Column(Integer, nullable=True)
    overall_confidence     = Column(String(50), nullable=True)
    review_required        = Column(Boolean, nullable=False, default=False)
    result_json            = Column(JSONB, nullable=True)
    edited_result_json     = Column(JSONB, nullable=True)
    last_edited_at         = Column(DateTime, nullable=True)
    last_edited_by         = Column(UUID(as_uuid=True),
                                    ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at             = Column(DateTime, default=datetime.utcnow)
    updated_at             = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student        = relationship("SAEStudent", back_populates="submission")
    publisher_user = relationship("User", foreign_keys=[publisher_user_id])
    last_editor    = relationship("User", foreign_keys=[last_edited_by])
