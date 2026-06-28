import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base
from app.database.models.enums import MaterialType


class Course(Base):
    __tablename__ = "courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(200))
    code = Column(String(50), nullable=True)
    section = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    department = Column(String(200), nullable=True)
    semester = Column(String(50), nullable=True)
    year = Column(Integer, nullable=True)
    syllabus_details = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True)
    is_deleted = Column(Boolean, default=False)
    is_public = Column(Boolean, default=False)
    allow_subscriber_sessions = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="courses_created")
    sessions = relationship("Session", back_populates="course", cascade="all, delete-orphan")
    students = relationship("User", secondary="course_students", back_populates="courses_enrolled")
    course_materials = relationship("CourseMaterial", back_populates="course", cascade="all, delete-orphan")
    access_codes = relationship("CourseAccessCode", back_populates="course", cascade="all, delete-orphan")


class CourseMaterial(Base):
    __tablename__ = "course_materials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    material_type = Column(SQLEnum(MaterialType), nullable=False)
    file_path = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    file_type = Column(String(50), nullable=True)
    url = Column(String(500), nullable=True)
    author = Column(String(255), nullable=True)
    publication_year = Column(Integer, nullable=True)
    publisher = Column(String(255), nullable=True)
    isbn = Column(String(20), nullable=True)
    doi = Column(String(100), nullable=True)
    additional_info = Column(JSONB, nullable=True)
    is_required = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    course = relationship("Course", back_populates="course_materials")
    session_materials = relationship(
        "SessionMaterial", back_populates="course_material", cascade="all, delete-orphan"
    )


class CourseStudent(Base):
    __tablename__ = "course_students"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    enrollment_date = Column(DateTime, default=datetime.utcnow)


class CourseAccessCode(Base):
    __tablename__ = "course_access_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code = Column(String(32), nullable=False, unique=True, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    max_uses = Column(Integer, nullable=True)
    uses_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    course = relationship("Course", back_populates="access_codes")
    creator = relationship("User", foreign_keys=[created_by])
