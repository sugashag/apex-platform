"""AiDraft request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.ai_draft import AiDraftStatus, AiDraftType
from app.utils.pagination import PaginatedResponse


class AiDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    agent_run_id: UUID | None
    draft_type: AiDraftType
    entity_type: str | None
    entity_id: UUID | None
    subject: str | None
    body_html: str | None
    body_text: str | None
    status: AiDraftStatus
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


AiDraftListResponse = PaginatedResponse[AiDraftResponse]


class DraftEditAndSendRequest(BaseModel):
    """Body for POST /drafts/{id}/edit-and-send."""

    subject: str | None = None
    body_html: str | None = None
    body_text: str | None = None
