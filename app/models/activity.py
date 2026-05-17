"""Activity model — a unified timeline event for a contact/deal/lead."""

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class ActivityType(enum.StrEnum):
    CALL = "call"
    EMAIL_SENT = "email_sent"
    EMAIL_RECEIVED = "email_received"
    NOTE = "note"
    STAGE_CHANGE = "stage_change"
    SCORE_UPDATE = "score_update"
    PAYMENT = "payment"
    SMS = "sms"
    MEETING = "meeting"
    TASK = "task"


class ActorType(enum.StrEnum):
    HUMAN = "human"
    AI_AGENT = "ai_agent"


class Activity(Base):
    """A timeline event. May be attached to a contact, deal, lead, or any combination."""

    __tablename__ = "activities"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=True,
    )
    deal_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("deals.id", ondelete="CASCADE"),
        nullable=True,
    )
    lead_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=True,
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    type: Mapped[ActivityType] = mapped_column(
        pg_enum(ActivityType, name="activity_type"),
        nullable=False,
    )
    actor_type: Mapped[ActorType] = mapped_column(
        pg_enum(ActorType, name="activity_actor_type"),
        nullable=False,
        default=ActorType.HUMAN,
    )
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `metadata` is reserved on DeclarativeBase, so use `meta` for the flexible JSON blob.
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_activities_contact_id", "contact_id"),
        Index("ix_activities_deal_id", "deal_id"),
        Index("ix_activities_type", "type"),
        Index("ix_activities_occurred_at", "occurred_at"),
    )
