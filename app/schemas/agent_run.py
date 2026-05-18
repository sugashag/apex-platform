"""AgentRun request/response schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.agent_run import AgentRunStatus, AgentType
from app.utils.pagination import PaginatedResponse


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    agent_type: AgentType
    trigger: str
    entity_type: str | None
    entity_id: UUID | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    model_used: str | None
    status: AgentRunStatus
    error_message: str | None
    output: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


AgentRunListResponse = PaginatedResponse[AgentRunResponse]


class DraftOutreachRequest(BaseModel):
    """Body for POST /agents/contacts/{contact_id}/draft-outreach."""

    step_instructions: str | None = None
