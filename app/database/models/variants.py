import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class Avatar3DModel(Base):
    """W2A: Admin-managed catalog of 3-D avatar models."""
    __tablename__ = "avatar_3d_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)
    preview_image_path = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by])
    variants = relationship("AvatarVariant", back_populates="model_3d", foreign_keys="AvatarVariant.model_3d_id")


class AvatarVariant(Base):
    """W2A: Publisher-defined variant of an avatar (language, voice, 3-D model override)."""
    __tablename__ = "avatar_variants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatars.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    model_3d_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatar_3d_models.id", ondelete="SET NULL"),
        nullable=True,
    )
    heygen_avatar_id = Column(String(200), nullable=True)
    heygen_voice_id = Column(String(200), nullable=True)
    language = Column(String(50), nullable=True, default="en", server_default="en")
    is_default = Column(Boolean, nullable=False, default=False, server_default="false")
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    avatar = relationship("Avatar", back_populates="variants")
    model_3d = relationship("Avatar3DModel", back_populates="variants", foreign_keys=[model_3d_id])
