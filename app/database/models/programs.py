import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class Program(Base):
    """W2B: A curated bundle of avatars and courses published as a learning program."""
    __tablename__ = "programs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    publisher_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    publisher = relationship("User", foreign_keys=[publisher_id])
    memberships = relationship("ProgramMembership", back_populates="program", cascade="all, delete-orphan")
    program_avatars = relationship("ProgramAvatar", back_populates="program", cascade="all, delete-orphan")
    program_courses = relationship("ProgramCourse", back_populates="program", cascade="all, delete-orphan")


class ProgramMembership(Base):
    """W2B: Subscriber enrollment in a program."""
    __tablename__ = "program_memberships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    program_id = Column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(50), nullable=False, default="member", server_default="member")
    joined_at = Column(DateTime, default=datetime.utcnow)

    program = relationship("Program", back_populates="memberships")
    user = relationship("User")


class ProgramAvatar(Base):
    """W2B: Avatar included in a program."""
    __tablename__ = "program_avatars"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    program_id = Column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    avatar_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatars.id", ondelete="CASCADE"),
        nullable=False,
    )
    added_at = Column(DateTime, default=datetime.utcnow)

    program = relationship("Program", back_populates="program_avatars")
    avatar = relationship("Avatar")


class ProgramCourse(Base):
    """W2B: Course included in a program."""
    __tablename__ = "program_courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    program_id = Column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    added_at = Column(DateTime, default=datetime.utcnow)

    program = relationship("Program", back_populates="program_courses")
    course = relationship("Course")
