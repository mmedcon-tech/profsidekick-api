from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


class MemoryGlobalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class MemoryConsentRequest(MemoryGlobalRequest):
    education_shared: bool = False


class MemoryItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: Optional[str] = Field(
        default=None, min_length=1, max_length=500, pattern=r"\S"
    )
    status: Optional[Literal["active", "resolved"]] = None


class MemoryItemResponse(BaseModel):
    id: str
    avatar_id: Optional[str]
    type: str
    topic: Optional[str]
    content: str
    evidence_quote: Optional[str] = None
    confidence: Optional[float]
    status: str
    visibility: list[str]
    consent_basis: Optional[str]
    created_at: datetime
    last_confirmed_at: Optional[datetime]
    expires_at: datetime
    times_seen: int


class MemoryTwinResponse(BaseModel):
    id: str
    name: str
    profession: str
    owned: bool
    enabled: bool
    education_shared: bool
    consented_at: Optional[datetime]


class MemoryDashboardResponse(BaseModel):
    enabled: bool
    twins: list[MemoryTwinResponse]
    items: list[MemoryItemResponse]


class MemoryCountResponse(BaseModel):
    type: str
    topic: Optional[str]
    count: int


class MemoryStudentResponse(BaseModel):
    id: str
    name: str


class MemoryExpertResponse(BaseModel):
    students: list[MemoryStudentResponse]
    items: list[MemoryItemResponse]
    counts: list[MemoryCountResponse]
