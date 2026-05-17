"""Company request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.utils.pagination import PaginatedResponse


class CompanyBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=100)
    employee_count: int | None = Field(default=None, ge=0)
    annual_revenue_cents: int | None = Field(default=None, ge=0)
    website: HttpUrl | None = None
    linkedin_url: HttpUrl | None = None
    netsuite_internal_id: str | None = Field(default=None, max_length=50)
    netsuite_external_id: str | None = Field(default=None, max_length=100)


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=100)
    employee_count: int | None = Field(default=None, ge=0)
    annual_revenue_cents: int | None = Field(default=None, ge=0)
    website: HttpUrl | None = None
    linkedin_url: HttpUrl | None = None
    netsuite_internal_id: str | None = Field(default=None, max_length=50)
    netsuite_external_id: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class CompanyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    domain: str | None
    industry: str | None
    employee_count: int | None
    annual_revenue_cents: int | None
    website: str | None
    linkedin_url: str | None
    netsuite_internal_id: str | None
    netsuite_external_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CompanyDetailResponse(CompanyResponse):
    """Company response with contact count."""

    contact_count: int


CompanyListResponse = PaginatedResponse[CompanyResponse]
