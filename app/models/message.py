"""Message model — an individual email message within a thread."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class MessageDirection(enum.StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Message(Base):
    """A single email message inside a thread."""

    __tablename__ = "messages"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_email: Mapped[str] = mapped_column(String(255), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_emails: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    cc_emails: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    direction: Mapped[MessageDirection] = mapped_column(
        pg_enum(MessageDirection, name="message_direction"),
        nullable=False,
    )
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resend_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ai_draft: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_messages_thread_id", "thread_id"),
        Index("ix_messages_direction", "direction"),
        Index("ix_messages_sent_at", "sent_at"),
    )
