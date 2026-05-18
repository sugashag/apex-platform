"""Workflow model — rule that fires on a trigger event."""

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
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


class WorkflowTriggerType(enum.StrEnum):
    LEAD_CREATED = "lead_created"
    LEAD_STATUS_CHANGED = "lead_status_changed"
    DEAL_STAGE_CHANGED = "deal_stage_changed"
    DEAL_CREATED = "deal_created"
    FORM_SUBMITTED = "form_submitted"
    CALL_COMPLETED = "call_completed"
    EMAIL_RECEIVED = "email_received"
    CONTACT_CREATED = "contact_created"
    PAYMENT_RECEIVED = "payment_received"
    SLA_BREACHED = "sla_breached"
    MANUAL = "manual"


class Workflow(Base):
    """A rules-based workflow: trigger + conditions + ordered steps."""

    __tablename__ = "workflows"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trigger_type: Mapped[WorkflowTriggerType] = mapped_column(
        pg_enum(WorkflowTriggerType, name="workflow_trigger_type"),
        nullable=False,
    )
    trigger_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_workflows_trigger_type", "trigger_type"),
        Index("ix_workflows_is_active", "is_active"),
    )
