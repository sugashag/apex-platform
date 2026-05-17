"""Pipeline stage request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.utils.pagination import PaginatedResponse


class PipelineStageBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    position: int = Field(..., ge=0)
    probability_default: int = Field(default=0, ge=0, le=100)
    is_won: bool = False
    is_lost: bool = False
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class PipelineStageCreate(PipelineStageBase):
    pass


class PipelineStageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    position: int | None = Field(default=None, ge=0)
    probability_default: int | None = Field(default=None, ge=0, le=100)
    is_won: bool | None = None
    is_lost: bool | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class PipelineStageReorderItem(BaseModel):
    id: UUID
    position: int = Field(..., ge=0)


class PipelineStageReorderRequest(BaseModel):
    stages: list[PipelineStageReorderItem] = Field(..., min_length=1)


class PipelineStageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    position: int
    probability_default: int
    is_won: bool
    is_lost: bool
    color: str | None
    created_at: datetime
    updated_at: datetime


PipelineStageListResponse = PaginatedResponse[PipelineStageResponse]
