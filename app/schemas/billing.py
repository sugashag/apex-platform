"""Billing / workspace-subscription schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.workspace_subscription import SubscriptionStatus
from app.schemas.plan import PlanResponse


class SubscriptionCreate(BaseModel):
    """Body for ``POST /billing/subscribe``."""

    plan_id: UUID
    billing_email: EmailStr
    billing_name: str = Field(..., min_length=1, max_length=255)


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    plan_id: UUID
    status: SubscriptionStatus
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    trial_ends_at: datetime | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancelled_at: datetime | None
    billing_email: str | None
    billing_name: str | None
    created_at: datetime
    updated_at: datetime
    plan: PlanResponse | None = None


class InvoiceSummary(BaseModel):
    """A flattened view of a Stripe invoice (best-effort)."""

    id: str
    amount_cents: int
    currency: str
    status: str
    hosted_invoice_url: str | None
    invoice_pdf: str | None
    created_at: datetime | None


class InvoiceListResponse(BaseModel):
    items: list[InvoiceSummary]
