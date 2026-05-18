"""Partner referral schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.partner_referral import PartnerReferralStatus


class PartnerReferralCreate(BaseModel):
    partner_name: str = Field(..., min_length=1, max_length=255)
    partner_email: EmailStr
    referral_code: str | None = Field(default=None, min_length=4, max_length=50)
    commission_rate: Decimal | None = Field(default=None, ge=0, le=100)
    notes: str | None = None


class PartnerReferralResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    partner_name: str
    partner_email: str
    referral_code: str
    referred_workspace_id: UUID | None
    status: PartnerReferralStatus
    commission_rate: Decimal
    commission_paid_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class PartnerReferralListResponse(BaseModel):
    items: list[PartnerReferralResponse]
