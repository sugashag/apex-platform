"""Call model — voice call record linked to contact/deal."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
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


class CallDirection(enum.StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallStatus(enum.StrEnum):
    INITIATED = "initiated"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    CANCELED = "canceled"


class CallSentiment(enum.StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class CallHandledBy(enum.StrEnum):
    AI_AGENT = "ai_agent"
    HUMAN = "human"
    AI_THEN_HUMAN = "ai_then_human"


class Call(Base):
    """A voice call. May be inbound or outbound; may be handled by AI or human."""

    __tablename__ = "calls"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    deal_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("deals.id", ondelete="SET NULL"),
        nullable=True,
    )
    initiated_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    twilio_call_sid: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True
    )
    direction: Mapped[CallDirection] = mapped_column(
        pg_enum(CallDirection, name="call_direction"),
        nullable=False,
    )
    status: Mapped[CallStatus] = mapped_column(
        pg_enum(CallStatus, name="call_status"),
        nullable=False,
        default=CallStatus.INITIATED,
    )
    from_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recording_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recording_sid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_sentiment: Mapped[CallSentiment | None] = mapped_column(
        pg_enum(CallSentiment, name="call_sentiment"),
        nullable=True,
    )
    ai_next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    handled_by: Mapped[CallHandledBy] = mapped_column(
        pg_enum(CallHandledBy, name="call_handled_by"),
        nullable=False,
        default=CallHandledBy.HUMAN,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_calls_contact_id", "contact_id"),
        Index("ix_calls_deal_id", "deal_id"),
        Index("ix_calls_status", "status"),
        Index("ix_calls_started_at", "started_at"),
    )
