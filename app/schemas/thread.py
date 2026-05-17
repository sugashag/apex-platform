"""Thread request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.thread import ThreadStatus
from app.schemas.message import MessageResponse
from app.utils.pagination import PaginatedResponse


class ThreadCreate(BaseModel):
    """Compose a new outbound thread (first message)."""

    subject: str | None = Field(default=None, max_length=500)
    contact_id: UUID | None = None
    deal_id: UUID | None = None
    email_account_id: UUID | None = None
    to_emails: list[EmailStr] = Field(min_length=1)
    cc_emails: list[EmailStr] | None = None
    body_text: str | None = None
    body_html: str | None = None


class ThreadAssign(BaseModel):
    assignee_id: UUID | None = None


class ThreadSnooze(BaseModel):
    snoozed_until: datetime


class ThreadReply(BaseModel):
    body_text: str | None = None
    body_html: str | None = None
    cc_emails: list[EmailStr] | None = None


class ThreadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    contact_id: UUID | None
    deal_id: UUID | None
    email_account_id: UUID | None
    subject: str | None
    assignee_id: UUID | None
    status: ThreadStatus
    snoozed_until: datetime | None
    sla_first_response_due_at: datetime | None
    sla_resolution_due_at: datetime | None
    first_responded_at: datetime | None
    resolved_at: datetime | None
    external_thread_id: str | None
    created_at: datetime
    updated_at: datetime

    contact_name: str | None = None
    assignee_name: str | None = None
    message_count: int = 0
    last_message_at: datetime | None = None


class ThreadDetailResponse(ThreadResponse):
    """Thread with all messages inlined."""

    messages: list[MessageResponse] = Field(default_factory=list)


ThreadListResponse = PaginatedResponse[ThreadResponse]
