"""Sequence request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.sequence_enrollment import SequenceEnrollmentStatus
from app.models.sequence_step import SequenceStepType
from app.utils.pagination import PaginatedResponse

# --- steps -------------------------------------------------------------------


class SequenceStepCreate(BaseModel):
    position: int = Field(ge=0)
    step_type: SequenceStepType
    delay_days: int = Field(default=0, ge=0)
    subject_template: str | None = Field(default=None, max_length=500)
    body_template: str | None = None


class SequenceStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence_id: UUID
    position: int
    step_type: SequenceStepType
    delay_days: int
    subject_template: str | None
    body_template: str | None


# --- sequences ---------------------------------------------------------------


class SequenceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_active: bool = True
    exit_on_reply: bool = True
    steps: list[SequenceStepCreate] = Field(default_factory=list)


class SequenceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    exit_on_reply: bool | None = None
    steps: list[SequenceStepCreate] | None = None


class SequenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    is_active: bool
    exit_on_reply: bool
    created_at: datetime
    updated_at: datetime


class SequenceDetailResponse(SequenceResponse):
    steps: list[SequenceStepResponse]
    enrollment_count: int


SequenceListResponse = PaginatedResponse[SequenceResponse]


# --- enrollments -------------------------------------------------------------


class SequenceEnrollRequest(BaseModel):
    contact_ids: list[UUID] = Field(min_length=1)
    deal_id: UUID | None = None


class SequenceEnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    sequence_id: UUID
    contact_id: UUID
    deal_id: UUID | None
    enrolled_by_id: UUID | None
    status: SequenceEnrollmentStatus
    current_step: int
    next_step_at: datetime | None
    exited_at: datetime | None
    created_at: datetime
    updated_at: datetime
