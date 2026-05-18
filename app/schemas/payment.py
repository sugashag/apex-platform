"""Payment request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.payment import PaymentStatus
from app.utils.pagination import PaginatedResponse


class PaymentCreate(BaseModel):
    deal_id: UUID | None = None
    contact_id: UUID | None = None
    amount_cents: int = Field(..., ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    description: str | None = Field(default=None, max_length=500)
    stripe_payment_intent_id: str | None = Field(default=None, max_length=255)
    stripe_customer_id: str | None = Field(default=None, max_length=255)
    status: PaymentStatus = PaymentStatus.PENDING


class PaymentIntentCreate(BaseModel):
    deal_id: UUID
    amount_cents: int = Field(..., gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    description: str | None = Field(default=None, max_length=500)


class PaymentIntentResponse(BaseModel):
    payment_id: UUID
    payment_intent_id: str
    client_secret: str
    amount_cents: int
    currency: str


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    deal_id: UUID | None
    contact_id: UUID | None
    stripe_payment_intent_id: str | None
    stripe_customer_id: str | None
    stripe_invoice_id: str | None
    stripe_subscription_id: str | None
    amount_cents: int
    currency: str
    status: PaymentStatus
    is_first_payment: bool
    description: str | None
    netsuite_transaction_id: str | None
    netsuite_invoice_id: str | None
    paid_at: datetime | None
    refunded_at: datetime | None
    created_at: datetime
    updated_at: datetime


PaymentListResponse = PaginatedResponse[PaymentResponse]
