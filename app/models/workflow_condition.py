"""WorkflowCondition model — filter that must pass for a workflow to run."""

import enum
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class WorkflowConditionOperator(enum.StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    IS_SET = "is_set"
    IS_NOT_SET = "is_not_set"


class WorkflowCondition(Base):
    """A single field/operator/value condition on a workflow."""

    __tablename__ = "workflow_conditions"

    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field: Mapped[str] = mapped_column(String(100), nullable=False)
    operator: Mapped[WorkflowConditionOperator] = mapped_column(
        pg_enum(WorkflowConditionOperator, name="workflow_condition_operator"),
        nullable=False,
    )
    value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
