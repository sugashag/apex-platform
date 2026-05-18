"""Stripe webhook handler — payment intents, invoices, subscriptions.

Webhook events drive the closing-of-the-funnel:
* ``payment_intent.succeeded`` — flips the Payment to succeeded, stamps
  ``Deal.first_payment_at`` if this is the deal's first paid payment, fires
  the ``payment_received`` workflow trigger, enqueues a NetSuite invoice sync.
* ``payment_intent.payment_failed`` — flips Payment to failed and drops an
  Activity row for the deal owner.
* ``invoice.paid`` — creates a Payment row if one isn't already mapped.
* ``customer.subscription.created`` — stamps the subscription id on any
  matching deal so future renewals are tracked.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import func, select

from app.dependencies import DbSession
from app.models.activity import Activity, ActivityType, ActorType
from app.models.deal import Deal
from app.models.payment import Payment, PaymentStatus
from app.services import billing_service, workflow_engine
from app.services.agent_queue import enqueue
from app.services.stripe_service import stripe_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/stripe", tags=["webhooks"])


def _parse_event_time(epoch_seconds: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(epoch_seconds), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


async def _load_payment_by_intent(
    db: DbSession, payment_intent_id: str
) -> Payment | None:
    result = await db.execute(
        select(Payment).where(
            Payment.stripe_payment_intent_id == payment_intent_id
        )
    )
    return result.scalar_one_or_none()


async def _handle_payment_succeeded(
    db: DbSession, event: dict[str, Any]
) -> None:
    obj = (event.get("data") or {}).get("object") or {}
    intent_id = obj.get("id")
    if not isinstance(intent_id, str):
        return

    payment = await _load_payment_by_intent(db, intent_id)
    if payment is None:
        # Webhook fired before APEX persisted the Payment record — derive
        # workspace/deal from the metadata Stripe stored on the intent.
        metadata = obj.get("metadata") or {}
        ws_raw = metadata.get("workspace_id")
        deal_raw = metadata.get("deal_id")
        if ws_raw is None:
            logger.warning(
                "payment_intent.succeeded missing workspace_id metadata for %s",
                intent_id,
            )
            return
        try:
            workspace_id = UUID(str(ws_raw))
            deal_id = UUID(str(deal_raw)) if deal_raw else None
        except ValueError:
            logger.warning("invalid uuid metadata on payment intent %s", intent_id)
            return

        deal = await db.get(Deal, deal_id) if deal_id else None
        payment = Payment(
            workspace_id=workspace_id,
            deal_id=deal_id,
            contact_id=deal.contact_id if deal is not None else None,
            stripe_payment_intent_id=intent_id,
            stripe_customer_id=obj.get("customer"),
            amount_cents=int(obj.get("amount_received") or obj.get("amount") or 0),
            currency=str(obj.get("currency") or "usd").upper(),
            status=PaymentStatus.PENDING,
        )
        db.add(payment)
        await db.flush()

    payment.status = PaymentStatus.SUCCEEDED
    payment.paid_at = _parse_event_time(event.get("created"))
    if obj.get("invoice"):
        payment.stripe_invoice_id = str(obj["invoice"])

    # Mark `is_first_payment` if no other succeeded payment exists for the deal.
    deal: Deal | None = None
    if payment.deal_id is not None:
        prior_result = await db.execute(
            select(func.count())
            .select_from(Payment)
            .where(
                Payment.deal_id == payment.deal_id,
                Payment.id != payment.id,
                Payment.status == PaymentStatus.SUCCEEDED,
            )
        )
        prior = int(prior_result.scalar_one())
        if prior == 0:
            payment.is_first_payment = True
            deal = await db.get(Deal, payment.deal_id)
            if deal is not None and deal.first_payment_at is None:
                deal.first_payment_at = payment.paid_at

    db.add(
        Activity(
            workspace_id=payment.workspace_id,
            deal_id=payment.deal_id,
            contact_id=payment.contact_id,
            actor_type=ActorType.HUMAN,
            type=ActivityType.PAYMENT,
            subject=(
                f"Payment received: ${payment.amount_cents / 100:.2f} "
                f"{payment.currency}"
            ),
            body=payment.description,
            occurred_at=payment.paid_at or datetime.now(UTC),
        )
    )

    if payment.is_first_payment:
        await workflow_engine.trigger_workflow(
            db,
            workspace_id=payment.workspace_id,
            trigger_type="payment_received",
            entity_type="payment",
            entity_id=payment.id,
            context={
                "payment_id": str(payment.id),
                "deal_id": (
                    str(payment.deal_id) if payment.deal_id else None
                ),
                "contact_id": (
                    str(payment.contact_id) if payment.contact_id else None
                ),
                "payment": {
                    "id": str(payment.id),
                    "amount_cents": payment.amount_cents,
                    "currency": payment.currency,
                    "is_first_payment": True,
                },
            },
        )

    await enqueue(
        "sync_payment_to_netsuite",
        payment.workspace_id,
        payment.id,
    )


async def _handle_payment_failed(db: DbSession, event: dict[str, Any]) -> None:
    obj = (event.get("data") or {}).get("object") or {}
    intent_id = obj.get("id")
    if not isinstance(intent_id, str):
        return
    payment = await _load_payment_by_intent(db, intent_id)
    if payment is None:
        return
    payment.status = PaymentStatus.FAILED
    db.add(
        Activity(
            workspace_id=payment.workspace_id,
            deal_id=payment.deal_id,
            contact_id=payment.contact_id,
            actor_type=ActorType.HUMAN,
            type=ActivityType.NOTE,
            subject="Payment failed",
            body=(
                obj.get("last_payment_error", {}).get("message")
                or "Stripe reported payment_intent.payment_failed"
            ),
        )
    )


async def _handle_invoice_paid(db: DbSession, event: dict[str, Any]) -> None:
    """Create / update a Payment record from an ``invoice.paid`` event."""
    obj = (event.get("data") or {}).get("object") or {}
    invoice_id = obj.get("id")
    if not isinstance(invoice_id, str):
        return

    intent_id = obj.get("payment_intent")
    payment: Payment | None = None
    if isinstance(intent_id, str):
        payment = await _load_payment_by_intent(db, intent_id)
    if payment is None:
        # Look up by invoice id alone — some events only carry the invoice.
        result = await db.execute(
            select(Payment).where(Payment.stripe_invoice_id == invoice_id)
        )
        payment = result.scalar_one_or_none()

    if payment is None:
        metadata = obj.get("metadata") or {}
        ws_raw = metadata.get("workspace_id")
        deal_raw = metadata.get("deal_id")
        if not ws_raw:
            return
        try:
            workspace_id = UUID(str(ws_raw))
            deal_id = UUID(str(deal_raw)) if deal_raw else None
        except ValueError:
            return
        deal = await db.get(Deal, deal_id) if deal_id else None
        payment = Payment(
            workspace_id=workspace_id,
            deal_id=deal_id,
            contact_id=deal.contact_id if deal is not None else None,
            stripe_invoice_id=invoice_id,
            stripe_payment_intent_id=(
                intent_id if isinstance(intent_id, str) else None
            ),
            stripe_customer_id=obj.get("customer"),
            amount_cents=int(obj.get("amount_paid") or 0),
            currency=str(obj.get("currency") or "usd").upper(),
            status=PaymentStatus.PENDING,
        )
        db.add(payment)
        await db.flush()

    payment.status = PaymentStatus.SUCCEEDED
    payment.paid_at = _parse_event_time(event.get("created"))
    payment.stripe_invoice_id = invoice_id


async def _handle_subscription_created(
    db: DbSession, event: dict[str, Any]
) -> None:
    """Stamp the subscription id on the most recent payment for the customer.

    Stripe identifies the subscription with ``id`` and the customer with
    ``customer``. We look up the most recent Payment for that customer (the
    one created when the intent was constructed) and persist the subscription
    id so renewals can be reconciled later.
    """
    obj = (event.get("data") or {}).get("object") or {}
    subscription_id = obj.get("id")
    customer_id = obj.get("customer")
    if not isinstance(subscription_id, str) or not isinstance(customer_id, str):
        return

    result = await db.execute(
        select(Payment)
        .where(Payment.stripe_customer_id == customer_id)
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    payment = result.scalar_one_or_none()
    if payment is not None:
        payment.stripe_subscription_id = subscription_id


@router.post("")
async def stripe_event(
    request: Request,
    db: DbSession,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
) -> dict[str, str]:
    body = await request.body()
    try:
        event = stripe_service.validate_webhook(body, stripe_signature)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    event_type = event.get("type") or ""
    obj = (event.get("data") or {}).get("object") or {}

    try:
        # APEX-platform billing events (workspace subscriptions) — handled first
        # so an ``invoice.paid`` flagged with ``apex_billing=true`` metadata
        # never falls through to the deal-payment path.
        if event_type in {
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "invoice.payment_failed",
        } or (
            event_type == "invoice.paid"
            and billing_service.is_billing_subscription_event(event_type, obj)
        ):
            updated = await billing_service.handle_subscription_event(
                db, event_type, obj
            )
            if updated is None and event_type == "invoice.paid":
                # Not a billing invoice — fall through to deal payment handler.
                await _handle_invoice_paid(db, event)
        elif event_type == "payment_intent.succeeded":
            await _handle_payment_succeeded(db, event)
        elif event_type == "payment_intent.payment_failed":
            await _handle_payment_failed(db, event)
        elif event_type == "invoice.paid":
            await _handle_invoice_paid(db, event)
        elif event_type == "customer.subscription.created":
            await _handle_subscription_created(db, event)
        else:
            return {"status": "ignored", "event": event_type}
    except Exception as exc:  # noqa: BLE001
        logger.exception("stripe webhook handler failed for %s", event_type)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="webhook handler failure",
        ) from exc

    await db.commit()
    return {"status": "ok", "event": event_type}
