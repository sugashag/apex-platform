"""Payment routes — manual entry, list, PaymentIntent creation."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.dependencies import CurrentUser, DbSession
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.payment import Payment, PaymentStatus
from app.schemas.payment import (
    PaymentCreate,
    PaymentIntentCreate,
    PaymentIntentResponse,
    PaymentListResponse,
    PaymentResponse,
)
from app.services.stripe_service import stripe_service
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/payments", tags=["payments"])


async def _load_deal(
    db: DbSession, deal_id: UUID, workspace_id: UUID
) -> Deal:
    result = await db.execute(
        select(Deal).where(
            Deal.id == deal_id, Deal.workspace_id == workspace_id
        )
    )
    deal = result.scalar_one_or_none()
    if deal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found"
        )
    return deal


@router.post(
    "", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED
)
async def create_payment(
    payload: PaymentCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> PaymentResponse:
    ws_id = current_user.workspace_id
    contact_id: UUID | None = payload.contact_id
    if payload.deal_id is not None:
        deal = await _load_deal(db, payload.deal_id, ws_id)
        if contact_id is None and deal.contact_id is not None:
            contact_id = deal.contact_id
    if contact_id is not None:
        result = await db.execute(
            select(Contact.id).where(
                Contact.id == contact_id, Contact.workspace_id == ws_id
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="contact_id is not in this workspace",
            )

    payment = Payment(
        workspace_id=ws_id,
        deal_id=payload.deal_id,
        contact_id=contact_id,
        amount_cents=payload.amount_cents,
        currency=payload.currency.upper(),
        description=payload.description,
        stripe_payment_intent_id=payload.stripe_payment_intent_id,
        stripe_customer_id=payload.stripe_customer_id,
        status=payload.status,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return PaymentResponse.model_validate(payment)


@router.get("", response_model=PaymentListResponse)
async def list_payments(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    deal_id: UUID | None = None,
    contact_id: UUID | None = None,
    payment_status: Annotated[
        PaymentStatus | None, Query(alias="status")
    ] = None,
    paid_from: Annotated[
        datetime | None, Query(description="paid_at >= this.")
    ] = None,
    paid_to: Annotated[
        datetime | None, Query(description="paid_at <= this.")
    ] = None,
) -> PaginatedResponse[PaymentResponse]:
    stmt = select(Payment).where(
        Payment.workspace_id == current_user.workspace_id
    )
    if deal_id is not None:
        stmt = stmt.where(Payment.deal_id == deal_id)
    if contact_id is not None:
        stmt = stmt.where(Payment.contact_id == contact_id)
    if payment_status is not None:
        stmt = stmt.where(Payment.status == payment_status)
    if paid_from is not None:
        stmt = stmt.where(Payment.paid_at >= paid_from)
    if paid_to is not None:
        stmt = stmt.where(Payment.paid_at <= paid_to)

    count_result = await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(Payment.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    rows = [PaymentResponse.model_validate(p) for p in result.scalars().all()]
    return PaginatedResponse.build(items=rows, total=total, params=pagination)


@router.post(
    "/create-intent",
    response_model=PaymentIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment_intent(
    payload: PaymentIntentCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> PaymentIntentResponse:
    ws_id = current_user.workspace_id
    deal = await _load_deal(db, payload.deal_id, ws_id)

    contact: Contact | None = None
    if deal.contact_id is not None:
        contact = await db.get(Contact, deal.contact_id)

    customer_id: str | None = None
    if contact is not None:
        customer_id = await stripe_service.create_customer(
            email=contact.email,
            name=(
                f"{contact.first_name or ''} {contact.last_name or ''}".strip()
                or None
            ),
            metadata={
                "workspace_id": str(ws_id),
                "contact_id": str(contact.id),
                "deal_id": str(deal.id),
            },
        )

    intent = await stripe_service.create_payment_intent(
        amount_cents=payload.amount_cents,
        currency=payload.currency,
        customer_id=customer_id,
        description=payload.description or deal.name,
        metadata={
            "workspace_id": str(ws_id),
            "deal_id": str(deal.id),
        },
    )

    payment = Payment(
        workspace_id=ws_id,
        deal_id=deal.id,
        contact_id=deal.contact_id,
        amount_cents=payload.amount_cents,
        currency=payload.currency.upper(),
        description=payload.description,
        stripe_payment_intent_id=intent["payment_intent_id"],
        stripe_customer_id=customer_id,
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    return PaymentIntentResponse(
        payment_id=payment.id,
        payment_intent_id=intent["payment_intent_id"],
        client_secret=intent["client_secret"],
        amount_cents=payment.amount_cents,
        currency=payment.currency,
    )


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> PaymentResponse:
    result = await db.execute(
        select(Payment).where(
            Payment.id == payment_id,
            Payment.workspace_id == current_user.workspace_id,
        )
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found"
        )
    return PaymentResponse.model_validate(payment)


# Separate router so we can register the deal-scoped lookup at the right prefix.
deals_router = APIRouter(prefix="/deals", tags=["payments"])


@deals_router.get(
    "/{deal_id}/payments", response_model=list[PaymentResponse]
)
async def list_payments_for_deal(
    deal_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> list[PaymentResponse]:
    await _load_deal(db, deal_id, current_user.workspace_id)
    result = await db.execute(
        select(Payment)
        .where(
            Payment.workspace_id == current_user.workspace_id,
            Payment.deal_id == deal_id,
        )
        .order_by(Payment.created_at.desc())
    )
    return [PaymentResponse.model_validate(p) for p in result.scalars().all()]
