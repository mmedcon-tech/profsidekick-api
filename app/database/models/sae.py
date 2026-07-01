"""
Self Assessment Exam (SAE) system models.
Completely isolated from the Math Placement Exam autograder.
Four tables: sae_assessments → sae_students → sae_invitation_tokens → sae_submissions
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy import UniqueConstraint

from app.database.connection import Base


class SAEAssessment(Base):
    """
    An exam event owned by a publisher.
    Optionally linked to a Course for integration with the rest of the platform.
    Students belong to an assessment, not just to a publisher pool.
    """
    __tablename__ = "sae_assessments"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
                          nullable=False, index=True)
    course_id    = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"),
                          nullable=True, index=True)
    name         = Column(String(200), nullable=False)
    description  = Column(Text, nullable=True)
    is_active    = Column(Boolean, nullable=False, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)

    publisher = relationship("User", foreign_keys=[publisher_id])
    course    = relationship("Course", foreign_keys=[course_id])
    students  = relationship("SAEStudent", back_populates="assessment")


class SAEStudent(Base):
    """
    A pre-created student slot managed by a publisher before the exam.
    Belongs to a specific SAEAssessment (and by denormalization, a publisher).
    user_id is NULL until the student activates their account via the
    one-time invitation link.
    """
    __tablename__ = "sae_students"
    __table_args__ = (
        UniqueConstraint("assessment_id", "student_number",
                         name="uq_sae_student_assessment_number"),
    )

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_number   = Column(Integer, nullable=False)
    student_code     = Column(String(20), unique=True, nullable=False, index=True)
    display_name     = Column(String(100), nullable=False)
    publisher_id     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
                              nullable=False, index=True)
    assessment_id    = Column(UUID(as_uuid=True), ForeignKey("sae_assessments.id", ondelete="RESTRICT"),
                              nullable=False, index=True)
    user_id          = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
                              nullable=True, index=True)
    is_activated     = Column(Boolean, nullable=False, default=False)
    activated_at     = Column(DateTime, nullable=True)
    has_submitted    = Column(Boolean, nullable=False, default=False)
    submitted_at     = Column(DateTime, nullable=True)
    submission_count = Column(Integer, nullable=False, default=0)
    # Educational background — collected during SAE account setup.
    country_of_origin = Column(String(100), nullable=True)
    curriculum        = Column(String(200), nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)

    publisher   = relationship("User", foreign_keys=[publisher_id])
    assessment  = relationship("SAEAssessment", foreign_keys=[assessment_id], back_populates="students")
    user        = relationship("User", foreign_keys=[user_id])
    invitation  = relationship("SAEInvitationToken", back_populates="student",
                               uselist=False, cascade="all, delete-orphan")
    # submission — viewonly accessor that always returns the single active submission.
    # Filtered by is_active so it returns at most one row even when multiple submissions exist.
    # DB-level ondelete=RESTRICT on the FK prevents accidental student deletion.
    submission  = relationship(
        "SAESubmission",
        primaryjoin=(
            "and_(SAEStudent.id == foreign(SAESubmission.student_id), "
            "SAESubmission.is_active == True)"
        ),
        uselist=False,
        viewonly=True,
        overlaps="submissions",
    )
    # submissions — ordered list of all submissions for history views.
    submissions = relationship(
        "SAESubmission",
        order_by="SAESubmission.submission_number",
        viewonly=True,
        overlaps="submission",
    )


class SAEInvitationToken(Base):
    """
    Setup link for an SAE student; usable at most twice.
    First use: create account (username + password).
    Second use: overwrite credentials if needed (e.g. typo in username).
    After the second successful use is_used is flipped to True permanently.
    token is a secrets.token_urlsafe(32) value (43 chars, 256-bit entropy).
    No email is ever sent — the publisher copies the URL and distributes it offline.
    """
    __tablename__ = "sae_invitation_tokens"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True),
                        ForeignKey("sae_students.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    token      = Column(String(64), unique=True, nullable=False, index=True)
    is_used    = Column(Boolean, nullable=False, default=False)
    use_count  = Column(Integer, nullable=False, default=0)
    used_at    = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("SAEStudent", back_populates="invitation")


class SAESubmission(Base):
    """
    One graded exam submission for an SAE student.
    Students may submit up to 5 times; each submission is preserved.
    submission_number is 1-based and increments per student.
    Only the most recent submission has is_active=True.
    UNIQUE(student_id, submission_number) enforced at the DB level.
    submitted_by_publisher=True means the publisher uploaded on behalf of the student.
    """
    __tablename__ = "sae_submissions"
    __table_args__ = (
        UniqueConstraint("student_id", "submission_number",
                         name="uq_sae_submission_student_number"),
    )

    id                     = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id             = Column(UUID(as_uuid=True), ForeignKey("sae_students.id",
                                    ondelete="RESTRICT"), nullable=False, index=True)
    submission_number      = Column(Integer, nullable=False)
    is_active              = Column(Boolean, nullable=False, default=True)
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

    student        = relationship("SAEStudent", overlaps="submission,submissions")
    publisher_user = relationship("User", foreign_keys=[publisher_user_id])
    last_editor    = relationship("User", foreign_keys=[last_edited_by])
