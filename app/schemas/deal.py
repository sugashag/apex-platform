"""Deal request/response schemas."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.deal import CloseReason
from app.schemas.activity import ActivityResponse
from app.schemas.company import CompanyResponse
from app.schemas.contact import ContactResponse
from app.utils.pagination import PaginatedResponse


class DealBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    contact_id: UUID | None = None
    company_id: UUID | None = None
    owner_id: UUID | None = None
    pipeline_stage_id: UUID | None = None
    value_cents: int | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    probability: int = Field(default=0, ge=0, le=100)
    expected_close_date: date | None = None


class DealCreate(DealBase):
    pass


class DealUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_id: UUID | None = None
    company_id: UUID | None = None
    owner_id: UUID | None = None
    pipeline_stage_id: UUID | None = None
    value_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    close_reason: CloseReason | None = None
    msa_signed_at: datetime | None = None
    first_payment_at: datetime | None = None
    netsuite_internal_id: str | None = Field(default=None, max_length=50)
    netsuite_external_id: str | None = Field(default=None, max_length=100)
    netsuite_customer_id: str | None = Field(default=None, max_length=50)
    netsuite_sales_order_id: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None


class DealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    contact_id: UUID | None
    company_id: UUID | None
    owner_id: UUID | None
    pipeline_stage_id: UUID | None
    name: str
    value_cents: int | None
    currency: str
    probability: int
    expected_close_date: date | None
    closed_at: datetime | None
    close_reason: CloseReason | None
    msa_signed_at: datetime | None
    first_payment_at: datetime | None
    netsuite_internal_id: str | None
    netsuite_external_id: str | None
    netsuite_customer_id: str | None
    netsuite_sales_order_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DealDetailResponse(DealResponse):
    """Deal with embedded contact, company, and recent activities."""

    contact: ContactResponse | None
    company: CompanyResponse | None
    recent_activities: list[ActivityResponse]


DealListResponse = PaginatedResponse[DealResponse]
