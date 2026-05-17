"""Deal model — an in-flight or closed sales opportunity."""

import enum
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class CloseReason(enum.StrEnum):
    WON = "won"
    LOST = "lost"
    NO_DECISION = "no_decision"


class Deal(Base):
    """A revenue opportunity. Lives on a pipeline stage until it closes."""

    __tablename__ = "deals"

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
    company_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    pipeline_stage_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pipeline_stages.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    probability: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    close_reason: Mapped[CloseReason | None] = mapped_column(
        pg_enum(CloseReason, name="deal_close_reason"),
        nullable=True,
    )
    msa_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    first_payment_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    netsuite_internal_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    netsuite_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    netsuite_customer_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    netsuite_sales_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_deals_contact_id", "contact_id"),
        Index("ix_deals_company_id", "company_id"),
        Index("ix_deals_owner_id", "owner_id"),
        Index("ix_deals_pipeline_stage_id", "pipeline_stage_id"),
        Index("ix_deals_closed_at", "closed_at"),
    )
