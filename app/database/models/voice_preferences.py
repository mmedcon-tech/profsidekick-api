import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class SubscriberVoicePreference(Base):
    """Dual voice pipeline — subscriber's optional override of the publisher's
    default avatar voice. One row per user; absence means "use the publisher
    default" (Pipeline A). `is_valid=False` marks a preference whose voice_id
    the provider no longer recognizes — cleared by
    voice_resolution_service.validate_and_clear_stale_preference().
    """

    __tablename__ = "subscriber_voice_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider = Column(String(20), nullable=False)  # 'openai' | 'elevenlabs'
    voice_id = Column(String(200), nullable=True)
    dialect = Column(String(50), nullable=True)
    is_valid = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
