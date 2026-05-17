"""Lead request/response schemas."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.lead import LeadStatus
from app.schemas.contact import ContactResponse
from app.utils.pagination import PaginatedResponse


class LeadCreate(BaseModel):
    contact_id: UUID
    owner_id: UUID | None = None
    status: LeadStatus = LeadStatus.NEW
    score: int = Field(default=0, ge=0)
    score_rationale: str | None = None
    source: str | None = Field(default=None, max_length=100)


class LeadUpdate(BaseModel):
    owner_id: UUID | None = None
    status: LeadStatus | None = None
    score: int | None = Field(default=None, ge=0)
    score_rationale: str | None = None
    source: str | None = Field(default=None, max_length=100)


class LeadConvertRequest(BaseModel):
    """Payload to convert a lead into a deal."""

    name: str = Field(..., min_length=1, max_length=255)
    pipeline_stage_id: UUID | None = None
    company_id: UUID | None = None
    owner_id: UUID | None = None
    value_cents: int | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    probability: int = Field(default=0, ge=0, le=100)
    expected_close_date: date | None = None


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    contact_id: UUID
    owner_id: UUID | None
    deal_id: UUID | None
    status: LeadStatus
    score: int
    score_rationale: str | None
    source: str | None
    converted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LeadDetailResponse(LeadResponse):
    """Lead with contact embedded."""

    contact: ContactResponse


LeadListResponse = PaginatedResponse[LeadResponse]
