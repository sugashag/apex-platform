"""SmsMessage model — an inbound or outbound SMS."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class SmsDirection(enum.StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class SmsStatus(enum.StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    RECEIVED = "received"


class SmsMessage(Base):
    """A single SMS, inbound or outbound, optionally linked to a contact."""

    __tablename__ = "sms_messages"

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
    twilio_message_sid: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True
    )
    direction: Mapped[SmsDirection] = mapped_column(
        pg_enum(SmsDirection, name="sms_direction"),
        nullable=False,
    )
    from_number: Mapped[str] = mapped_column(String(30), nullable=False)
    to_number: Mapped[str] = mapped_column(String(30), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SmsStatus] = mapped_column(
        pg_enum(SmsStatus, name="sms_status"),
        nullable=False,
        default=SmsStatus.QUEUED,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_sms_messages_contact_id", "contact_id"),
        Index("ix_sms_messages_direction", "direction"),
    )
