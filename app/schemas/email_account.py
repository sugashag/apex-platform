"""EmailAccount request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.email_account import EmailProvider
from app.utils.pagination import PaginatedResponse


class EmailAccountCreate(BaseModel):
    email_address: EmailStr
    display_name: str | None = Field(default=None, max_length=255)
    provider: EmailProvider
    access_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: datetime | None = None


class EmailAccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    access_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: datetime | None = None
    is_active: bool | None = None
    last_synced_at: datetime | None = None


class EmailAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    email_address: EmailStr
    display_name: str | None
    provider: EmailProvider
    is_active: bool
    last_synced_at: datetime | None
    token_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


EmailAccountListResponse = PaginatedResponse[EmailAccountResponse]
