"""W7: Renamed from Publisher* to Assistant* to support multi-role conversations.

Backward-compatible aliases (PublisherConversation, PublisherMessage) are kept at
the bottom of this file so existing imports continue to resolve without changes.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class AssistantConversation(Base):
    """Multi-role conversation container (publisher, subscriber, admin).

    context_type discriminates between roles; program_id optionally links
    subscriber conversations to a specific program's context.
    """
    __tablename__ = "assistant_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=True)
    program_id = Column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="SET NULL"),
        nullable=True,
    )
    context_type = Column(String(50), nullable=False, default="publisher", server_default="publisher")
    title = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    avatar = relationship("Avatar")
    program = relationship("Program", foreign_keys=[program_id])
    messages = relationship(
        "AssistantMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AssistantMessage.created_at",
    )


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assistant_conversations.id"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("AssistantConversation", back_populates="messages")


class FeedbackPreference(Base):
    """Stores which AI response a publisher chose as better."""
    __tablename__ = "feedback_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=True)
    prompt = Column(Text, nullable=False)
    selected_response = Column(Text, nullable=False)
    rejected_responses = Column(JSONB, nullable=False, default=list)
    feedback_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    publisher = relationship("User", foreign_keys=[publisher_id])
    avatar = relationship("Avatar")


class PublisherPreference(Base):
    """Key-value store for per-publisher settings."""
    __tablename__ = "publisher_preferences"
    __table_args__ = (UniqueConstraint("publisher_id", "key", name="uq_publisher_preference"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    key = Column(String(100), nullable=False)
    value = Column(JSONB, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)

    publisher = relationship("User", foreign_keys=[publisher_id])


class AvatarSubscription(Base):
    """Many-to-many join between subscribers and published avatars."""
    __tablename__ = "avatar_subscriptions"
    __table_args__ = (UniqueConstraint("subscriber_id", "avatar_id", name="uq_avatar_subscription"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscriber_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    avatar_id = Column(
        UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscribed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    expires_at = Column(DateTime, nullable=True)

    subscriber = relationship("User", foreign_keys=[subscriber_id])
    avatar = relationship("Avatar", foreign_keys=[avatar_id])


class PublisherMessageFeedback(Base):
    """Per-message thumbs-up/down + optional comment from publishers."""
    __tablename__ = "publisher_message_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assistant_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    avatar_id = Column(
        UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rating = Column(String(20), nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    message = relationship("AssistantMessage")
    publisher = relationship("User", foreign_keys=[publisher_id])


class PublisherResponseEdit(Base):
    """Tracks publisher inline edits to AI-generated responses."""
    __tablename__ = "publisher_response_edits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assistant_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    avatar_id = Column(
        UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id = Column(String(100), nullable=True, index=True)
    original_content = Column(Text, nullable=False)
    edited_content = Column(Text, nullable=False)
    edit_type = Column(String(50), nullable=False, default="publisher_refinement")
    created_at = Column(DateTime, default=datetime.utcnow)

    message = relationship("AssistantMessage")
    publisher = relationship("User", foreign_keys=[publisher_id])
    avatar = relationship("Avatar", foreign_keys=[avatar_id])


# Backward-compatible aliases — publisher_chat_service and any other callers
# that were written before the rename can continue importing these names.
PublisherConversation = AssistantConversation
PublisherMessage = AssistantMessage
