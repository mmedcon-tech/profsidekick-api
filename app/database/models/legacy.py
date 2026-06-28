"""
Stub models for dormant v1 services that import from app.database.models
but whose routers are not registered in main.py.

These stubs prevent ImportError if those services are ever loaded.
Do not extend or use these for new features.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.connection import Base


class ProfessorPersona(Base):
    """Stub: used by persona_service.py (professor/api.py not registered in main.py)."""
    __tablename__ = "professor_personas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    system_prompt = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
