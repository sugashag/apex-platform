"""SequenceStep model — one step in a Sequence."""

import enum
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class SequenceStepType(enum.StrEnum):
    EMAIL = "email"
    SMS = "sms"
    CALL_TASK = "call_task"
    AI_DRAFT_EMAIL = "ai_draft_email"


class SequenceStep(Base):
    """An ordered step (email/SMS/task) inside a Sequence."""

    __tablename__ = "sequence_steps"

    sequence_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sequences.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[SequenceStepType] = mapped_column(
        pg_enum(SequenceStepType, name="sequence_step_type"),
        nullable=False,
    )
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subject_template: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_sequence_steps_sequence_id", "sequence_id"),
        Index("ix_sequence_steps_position", "position"),
    )
