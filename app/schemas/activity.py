"""Activity request/response schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.activity import ActivityType, ActorType
from app.utils.pagination import PaginatedResponse


class ActivityCreate(BaseModel):
    type: ActivityType
    contact_id: UUID | None = None
    deal_id: UUID | None = None
    lead_id: UUID | None = None
    actor_type: ActorType = ActorType.HUMAN
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = None
    meta: dict[str, Any] | None = None
    occurred_at: datetime | None = None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    contact_id: UUID | None
    deal_id: UUID | None
    lead_id: UUID | None
    actor_id: UUID | None
    type: ActivityType
    actor_type: ActorType
    subject: str | None
    body: str | None
    meta: dict[str, Any] | None
    occurred_at: datetime
    created_at: datetime
    updated_at: datetime


ActivityListResponse = PaginatedResponse[ActivityResponse]
