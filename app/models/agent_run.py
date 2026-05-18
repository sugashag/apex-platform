"""AgentRun model — audit log for every AI agent invocation."""

import enum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class AgentType(enum.StrEnum):
    LEAD_SCORER = "lead_scorer"
    CALL_SUMMARIZER = "call_summarizer"
    OUTBOUND_DRAFTER = "outbound_drafter"
    REPLY_DRAFTER = "reply_drafter"
    TICKET_ROUTER = "ticket_router"
    OBJECTION_HANDLER = "objection_handler"
    PIPELINE_FORECASTER = "pipeline_forecaster"


class AgentRunStatus(enum.StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRun(Base):
    """One invocation of an AI agent, with cost + latency tracking."""

    __tablename__ = "agent_runs"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_type: Mapped[AgentType] = mapped_column(
        pg_enum(AgentType, name="agent_type"),
        nullable=False,
    )
    trigger: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        pg_enum(AgentRunStatus, name="agent_run_status"),
        nullable=False,
        default=AgentRunStatus.RUNNING,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_agent_runs_workspace_id", "workspace_id"),
        Index("ix_agent_runs_agent_type", "agent_type"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_created_at", "created_at"),
    )
