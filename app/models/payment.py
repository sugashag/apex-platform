"""Payment model — money in. Tied to a deal/contact and to a Stripe charge."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class PaymentStatus(enum.StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class Payment(Base):
    """A payment record. One row per Stripe PaymentIntent / Invoice."""

    __tablename__ = "payments"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    deal_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("deals.id", ondelete="SET NULL"),
        nullable=True,
    )
    contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
    )

    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[PaymentStatus] = mapped_column(
        pg_enum(PaymentStatus, name="payment_status"),
        nullable=False,
        default=PaymentStatus.PENDING,
    )
    is_first_payment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    netsuite_transaction_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    netsuite_invoice_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refunded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_payments_workspace_id", "workspace_id"),
        Index("ix_payments_deal_id", "deal_id"),
        Index("ix_payments_contact_id", "contact_id"),
        Index("ix_payments_status", "status"),
        Index("ix_payments_stripe_customer_id", "stripe_customer_id"),
    )
