"""Call request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.call import (
    CallDirection,
    CallHandledBy,
    CallSentiment,
    CallStatus,
)
from app.utils.pagination import PaginatedResponse


class CallCreate(BaseModel):
    """Initiate outbound call."""

    to_number: str = Field(min_length=1, max_length=30)
    from_number: str | None = Field(default=None, max_length=30)
    contact_id: UUID | None = None
    deal_id: UUID | None = None


class CallUpdate(BaseModel):
    status: CallStatus | None = None
    duration_seconds: int | None = None
    recording_url: str | None = Field(default=None, max_length=500)
    recording_sid: str | None = Field(default=None, max_length=100)
    transcript: str | None = None
    ai_summary: str | None = None
    ai_sentiment: CallSentiment | None = None
    ai_next_action: str | None = None
    handled_by: CallHandledBy | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class CallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    contact_id: UUID | None
    deal_id: UUID | None
    initiated_by_id: UUID | None
    twilio_call_sid: str | None
    direction: CallDirection
    status: CallStatus
    from_number: str | None
    to_number: str | None
    duration_seconds: int | None
    recording_url: str | None
    recording_sid: str | None
    transcript: str | None
    ai_summary: str | None
    ai_sentiment: CallSentiment | None
    ai_next_action: str | None
    handled_by: CallHandledBy
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_formatted(self) -> str | None:
        if self.duration_seconds is None:
            return None
        minutes, seconds = divmod(self.duration_seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"


class CallTokenResponse(BaseModel):
    """Twilio Client capability token for the WebRTC softphone."""

    token: str
    identity: str
    expires_in_seconds: int


CallListResponse = PaginatedResponse[CallResponse]
