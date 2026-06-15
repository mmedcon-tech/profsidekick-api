import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class AvatarAccessCode(Base):
    """W3: Publisher-issued access code scoped to a specific avatar (R46).

    Redeeming a code atomically creates an avatar subscription, enrolls the
    subscriber in all linked courses and programs, and optionally grants
    credits (R48).
    """

    __tablename__ = "avatar_access_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatars.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    code = Column(String(50), nullable=False, unique=True, index=True)
    max_users = Column(Integer, nullable=False)
    users_count = Column(Integer, nullable=False, default=0, server_default="0")
    credits_per_user = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    avatar = relationship("Avatar", back_populates="access_codes")
    creator = relationship("User", foreign_keys=[created_by])
    redemptions = relationship(
        "AvatarAccessCodeRedemption",
        back_populates="access_code",
        cascade="all, delete-orphan",
    )


class AvatarAccessCodeRedemption(Base):
    """W3: Audit log of avatar access code redemptions (R47).

    One row per (user, code) pair — unique constraint prevents double-redemption.
    """

    __tablename__ = "avatar_access_code_redemptions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "avatar_access_code_id",
            name="uq_avatar_code_redemption_user_code",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_access_code_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatar_access_codes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    redeemed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    credits_granted = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")

    access_code = relationship("AvatarAccessCode", back_populates="redemptions")
    user = relationship("User", foreign_keys=[user_id])
