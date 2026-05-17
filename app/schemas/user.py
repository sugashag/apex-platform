"""User and auth schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserRegister(BaseModel):
    """Self-service registration creates a user *and* their workspace."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    workspace_name: str = Field(..., min_length=1, max_length=255)
    workspace_slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    email: EmailStr
    first_name: str | None
    last_name: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
