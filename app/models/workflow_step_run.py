"""WorkflowStepRun model — execution record for a step within a WorkflowRun."""

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class WorkflowStepRunStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    SKIPPED = "skipped"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowStepRun(Base):
    """Per-step execution record for a WorkflowRun."""

    __tablename__ = "workflow_step_runs"

    workflow_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_step_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_steps.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[WorkflowStepRunStatus] = mapped_column(
        pg_enum(WorkflowStepRunStatus, name="workflow_step_run_status"),
        nullable=False,
        default=WorkflowStepRunStatus.PENDING,
    )
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    execute_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_workflow_step_runs_workflow_run_id", "workflow_run_id"),
        Index("ix_workflow_step_runs_status", "status"),
        Index("ix_workflow_step_runs_execute_at", "execute_at"),
    )
