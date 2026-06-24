import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, JSON
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base

class Student(Base):
    __tablename__ = "students"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_code = Column(String(20), unique=True, nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    created_by   = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by])
    submissions = relationship(
        "AutograderSubmission",
        back_populates="student",
        foreign_keys="[AutograderSubmission.student_id]",
        order_by="AutograderSubmission.version_number",
    )


class AutograderSubmission(Base):
    __tablename__ = "autograder_submissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Phase 3 columns
    student_id     = Column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="RESTRICT"), nullable=True)
    version_number = Column(Integer, nullable=True)
    submitted_by   = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)

    handwritten_filename  = Column(String(255), nullable=True)
    handwritten_file_path = Column(String(500), nullable=True)
    webassign_filename    = Column(String(255), nullable=True)
    webassign_file_path   = Column(String(500), nullable=True)

    # Legacy columns (kept until Phase 5)
    student_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    student_net_id  = Column(String(100), nullable=False)
    student_name    = Column(String(255), nullable=False)
    filename        = Column(String(255), nullable=True)
    file_path       = Column(String(500), nullable=True)

    score              = Column(Integer, nullable=True)
    overall_confidence = Column(String(50), nullable=True)
    review_required    = Column(Boolean, default=False)
    result_json        = Column(JSONB, nullable=False)
    is_active          = Column(Boolean, nullable=False, default=True, server_default="true")

    created_at = Column(DateTime, default=datetime.utcnow)

    student      = relationship("Student", foreign_keys=[student_id], back_populates="submissions")
    student_user = relationship("User", foreign_keys=[student_user_id])
    operator     = relationship("User", foreign_keys=[submitted_by])
