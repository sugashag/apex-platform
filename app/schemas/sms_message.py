"""SMS request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.sms_message import SmsDirection, SmsStatus
from app.utils.pagination import PaginatedResponse


class SmsMessageCreate(BaseModel):
    to_number: str = Field(min_length=1, max_length=30)
    body: str = Field(min_length=1)
    from_number: str | None = Field(default=None, max_length=30)
    contact_id: UUID | None = None


class SmsMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    contact_id: UUID | None
    twilio_message_sid: str | None
    direction: SmsDirection
    from_number: str
    to_number: str
    body: str
    status: SmsStatus
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


SmsMessageListResponse = PaginatedResponse[SmsMessageResponse]
