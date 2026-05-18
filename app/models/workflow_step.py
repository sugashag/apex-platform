"""WorkflowStep model — a single action within a workflow."""

import enum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class WorkflowActionType(enum.StrEnum):
    SEND_EMAIL = "send_email"
    SEND_SMS = "send_sms"
    CREATE_TASK = "create_task"
    ASSIGN_OWNER = "assign_owner"
    UPDATE_FIELD = "update_field"
    ADD_TAG = "add_tag"
    NOTIFY_USER = "notify_user"
    WAIT = "wait"
    HUMAN_GATE = "human_gate"
    TRIGGER_AGENT = "trigger_agent"
    CREATE_ACTIVITY = "create_activity"
    CHANGE_DEAL_STAGE = "change_deal_stage"


class WorkflowStep(Base):
    """An ordered action within a Workflow."""

    __tablename__ = "workflow_steps"

    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[WorkflowActionType] = mapped_column(
        pg_enum(WorkflowActionType, name="workflow_action_type"),
        nullable=False,
    )
    action_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    __table_args__ = (
        Index("ix_workflow_steps_workflow_id", "workflow_id"),
        Index("ix_workflow_steps_position", "position"),
    )
