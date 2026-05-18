"""AssignmentRule model — rules for auto-assigning threads to users."""

import enum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class AssignmentConditionOperator(enum.StrEnum):
    EQUALS = "equals"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"


class AssignmentRule(Base):
    """An ordered rule evaluated against incoming threads."""

    __tablename__ = "assignment_rules"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_field: Mapped[str] = mapped_column(String(100), nullable=False)
    condition_operator: Mapped[AssignmentConditionOperator] = mapped_column(
        pg_enum(AssignmentConditionOperator, name="assignment_condition_operator"),
        nullable=False,
    )
    condition_value: Mapped[str] = mapped_column(String(500), nullable=False)
    assign_to_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
