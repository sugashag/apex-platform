"""PartnerReferral — VAR partner referral tracking."""

import enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class PartnerReferralStatus(enum.StrEnum):
    PENDING = "pending"
    SIGNED_UP = "signed_up"
    PAYING = "paying"
    CHURNED = "churned"


class PartnerReferral(Base):
    """A VAR partner referral. Tracks status and commission accrual."""

    __tablename__ = "partner_referrals"

    partner_name: Mapped[str] = mapped_column(String(255), nullable=False)
    partner_email: Mapped[str] = mapped_column(String(255), nullable=False)
    referral_code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    referred_workspace_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[PartnerReferralStatus] = mapped_column(
        pg_enum(PartnerReferralStatus, name="partner_referral_status"),
        nullable=False,
        default=PartnerReferralStatus.PENDING,
    )
    commission_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("20.00")
    )
    commission_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
