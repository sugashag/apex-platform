"""Contact request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.contact import EmailStatus
from app.schemas.activity import ActivityResponse
from app.utils.pagination import PaginatedResponse


class ContactBase(BaseModel):
    email: EmailStr
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=150)
    company_id: UUID | None = None
    owner_id: UUID | None = None
    lead_score: int = Field(default=0, ge=0)
    source: str | None = Field(default=None, max_length=100)
    source_campaign: str | None = Field(default=None, max_length=255)
    source_medium: str | None = Field(default=None, max_length=100)
    source_term: str | None = Field(default=None, max_length=255)
    source_content: str | None = Field(default=None, max_length=255)
    first_seen_at: datetime | None = None
    email_status: EmailStatus = EmailStatus.ACTIVE
    netsuite_internal_id: str | None = Field(default=None, max_length=50)
    netsuite_external_id: str | None = Field(default=None, max_length=100)


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=150)
    company_id: UUID | None = None
    owner_id: UUID | None = None
    lead_score: int | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, max_length=100)
    source_campaign: str | None = Field(default=None, max_length=255)
    source_medium: str | None = Field(default=None, max_length=100)
    source_term: str | None = Field(default=None, max_length=255)
    source_content: str | None = Field(default=None, max_length=255)
    first_seen_at: datetime | None = None
    email_status: EmailStatus | None = None
    netsuite_internal_id: str | None = Field(default=None, max_length=50)
    netsuite_external_id: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    company_id: UUID | None
    owner_id: UUID | None
    email: EmailStr
    first_name: str | None
    last_name: str | None
    phone: str | None
    title: str | None
    lead_score: int
    source: str | None
    source_campaign: str | None
    source_medium: str | None
    source_term: str | None
    source_content: str | None
    first_seen_at: datetime | None
    email_status: EmailStatus
    netsuite_internal_id: str | None
    netsuite_external_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ContactDetailResponse(ContactResponse):
    """Contact response with last-N activities embedded."""

    recent_activities: list[ActivityResponse]


ContactListResponse = PaginatedResponse[ContactResponse]
