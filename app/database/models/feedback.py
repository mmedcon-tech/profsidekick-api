import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class SessionFeedback(Base):
    """W1B: Subscriber end-of-session rating and qualitative feedback."""
    __tablename__ = "session_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("session_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True)
    overall_rating = Column(Integer, nullable=True)
    clarity_rating = Column(Integer, nullable=True)
    helpfulness_rating = Column(Integer, nullable=True)
    engagement_rating = Column(Integer, nullable=True)
    comments = Column(Text, nullable=True)
    tags = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session_run = relationship("SessionRun")
    user = relationship("User")
    avatar = relationship("Avatar")


class TranscriptFeedback(Base):
    """W1B: Inline per-turn feedback on session transcript turns."""
    __tablename__ = "transcript_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("session_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    turn_index = Column(Integer, nullable=False)
    rating = Column(String(20), nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session_run = relationship("SessionRun")
    user = relationship("User")


class SessionPersonaSwitch(Base):
    """W1B: Log of subscriber persona/variant switches during a session run."""
    __tablename__ = "session_persona_switches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("session_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    from_persona = Column(String(100), nullable=True)
    to_persona = Column(String(100), nullable=False)
    switched_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reason = Column(String(255), nullable=True)

    session_run = relationship("SessionRun")
    user = relationship("User")
