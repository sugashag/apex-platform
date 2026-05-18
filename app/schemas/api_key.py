"""API key schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    scopes: list[str] | None = Field(default=None)
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    """Listing view — never exposes the full key."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    created_by_id: UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    expires_at: datetime | None
    is_active: bool
    scopes: list[str] | None
    created_at: datetime
    updated_at: datetime


class ApiKeyCreateResponse(ApiKeyResponse):
    """Creation view — returns the plaintext key exactly once."""

    full_key: str


class ApiKeyListResponse(BaseModel):
    items: list[ApiKeyResponse]
