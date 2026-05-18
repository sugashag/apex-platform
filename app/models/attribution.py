"""Attribution model — one row per significant touchpoint for a Contact.

Touch types:
- first_touch — the very first session/touchpoint we have for the Contact
- last_touch  — most recent meaningful touchpoint
- assisted    — any non-first/non-last touchpoint that contributed

When a Deal closes, `deal_id` is backfilled on every Attribution row for
the deal's Contact (see `attribution_service.link_deal_to_attributions`).
"""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class TouchType(enum.StrEnum):
    FIRST_TOUCH = "first_touch"
    LAST_TOUCH = "last_touch"
    ASSISTED = "assisted"


class Attribution(Base):
    __tablename__ = "attributions"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    deal_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("deals.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("visitor_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    touch_type: Mapped[TouchType] = mapped_column(
        pg_enum(TouchType, name="attribution_touch_type"),
        nullable=False,
    )
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    campaign: Mapped[str | None] = mapped_column(String(255), nullable=True)
    medium: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content: Mapped[str | None] = mapped_column(String(255), nullable=True)
    term: Mapped[str | None] = mapped_column(String(255), nullable=True)
    landing_page_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    referrer_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    gclid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fbclid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_attributions_contact_id", "contact_id"),
        Index("ix_attributions_deal_id", "deal_id"),
        Index("ix_attributions_touch_type", "touch_type"),
        Index("ix_attributions_source", "source"),
        Index("ix_attributions_occurred_at", "occurred_at"),
    )
