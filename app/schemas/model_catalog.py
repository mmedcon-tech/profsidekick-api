from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ModelType = Literal["heygen", "ready_player_me", "three_js", "custom"]
ModelGender = Literal["male", "female", "neutral"]


class Avatar3DModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    model_type: ModelType = "three_js"
    model_url: str = Field(min_length=1, max_length=500)
    thumbnail_url: str | None = Field(default=None, max_length=500)
    gender: ModelGender = "neutral"
    supported_languages: list[str] = Field(default_factory=lambda: ["en"])
    sort_order: int = 0
    is_active: bool = True


class Avatar3DModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    model_type: ModelType | None = None
    model_url: str | None = Field(default=None, min_length=1, max_length=500)
    thumbnail_url: str | None = Field(default=None, max_length=500)
    gender: ModelGender | None = None
    supported_languages: list[str] | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class Avatar3DModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    model_type: ModelType
    model_url: str
    thumbnail_url: str | None
    file_path: str
    preview_image_path: str | None
    gender: ModelGender
    supported_languages: list[str]
    sort_order: int
    is_active: bool
    created_at: datetime


class Avatar3DModelListResponse(BaseModel):
    models: list[Avatar3DModelResponse]
