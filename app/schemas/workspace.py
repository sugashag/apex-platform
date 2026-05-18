"""Workspace request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    is_active: bool
    tracking_token: str | None = None
    created_at: datetime
    updated_at: datetime


class TrackingSnippetResponse(BaseModel):
    """Marketing-site JS snippet for a workspace."""

    tracking_token: str
    api_base_url: str
    snippet: str
