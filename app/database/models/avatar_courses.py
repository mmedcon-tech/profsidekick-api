import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class AvatarCourse(Base):
    """W3: Links an avatar to a course (R50).

    When a subscriber subscribes to the avatar, they are automatically
    enrolled in every course linked here (R51, R57).
    Publishers manage these links via the avatar-courses API.
    """

    __tablename__ = "avatar_courses"
    __table_args__ = (
        UniqueConstraint("avatar_id", "course_id", name="uq_avatar_courses_avatar_course"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatars.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    avatar = relationship("Avatar", back_populates="avatar_courses")
    course = relationship("Course")
