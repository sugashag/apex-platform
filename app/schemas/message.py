"""Message request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.message import MessageDirection
from app.utils.pagination import PaginatedResponse


class MessageCreate(BaseModel):
    """Outbound reply payload."""

    body_text: str | None = None
    body_html: str | None = None
    cc_emails: list[EmailStr] | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    thread_id: UUID
    from_email: str
    from_name: str | None
    to_emails: list[str]
    cc_emails: list[str] | None
    direction: MessageDirection
    body_text: str | None
    body_html: str | None
    external_message_id: str | None
    resend_message_id: str | None
    ai_draft: bool
    sent_at: datetime | None
    opened_at: datetime | None
    clicked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    thread_subject: str | None = Field(default=None)


MessageListResponse = PaginatedResponse[MessageResponse]
