"""Billing routes — plan catalog, subscribe, cancel, invoices."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.dependencies import CurrentUser, DbSession
from app.middleware.rbac import require_admin
from app.models.plan import Plan
from app.models.user import User
from app.schemas.billing import (
    InvoiceListResponse,
    InvoiceSummary,
    SubscriptionCreate,
    SubscriptionResponse,
)
from app.schemas.plan import PlanResponse
from app.services import billing_service
from app.services.stripe_service import stripe_service

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(db: DbSession) -> list[Plan]:
    """List public, active plans. Open endpoint — no auth required."""
    result = await db.execute(
        select(Plan)
        .where(Plan.is_active.is_(True), Plan.is_public.is_(True))
        .order_by(Plan.price_cents_monthly.asc())
    )
    return list(result.scalars().all())


async def _serialize_subscription(db: DbSession, sub: Any) -> SubscriptionResponse:
    plan = await db.get(Plan, sub.plan_id)
    plan_payload = PlanResponse.model_validate(plan) if plan is not None else None
    payload = SubscriptionResponse.model_validate(sub)
    payload.plan = plan_payload
    return payload


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    db: DbSession, current_user: CurrentUser
) -> SubscriptionResponse:
    sub = await billing_service.get_subscription(db, current_user.workspace_id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription on file for this workspace",
        )
    return await _serialize_subscription(db, sub)


@router.post("/subscribe", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def subscribe(
    payload: SubscriptionCreate,
    db: DbSession,
    admin: User = Depends(require_admin()),
) -> SubscriptionResponse:
    """Create (or replace) the workspace's APEX subscription."""
    try:
        sub = await billing_service.create_subscription(
            db,
            workspace_id=admin.workspace_id,
            plan_id=payload.plan_id,
            billing_email=payload.billing_email,
            billing_name=payload.billing_name,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    await db.commit()
    await db.refresh(sub)
    return await _serialize_subscription(db, sub)


@router.post("/cancel", response_model=SubscriptionResponse)
async def cancel(
    db: DbSession,
    admin: User = Depends(require_admin()),
) -> SubscriptionResponse:
    try:
        sub = await billing_service.cancel_subscription(db, admin.workspace_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    await db.commit()
    await db.refresh(sub)
    return await _serialize_subscription(db, sub)


@router.get("/invoices", response_model=InvoiceListResponse)
async def list_invoices(
    db: DbSession,
    current_user: CurrentUser,
) -> InvoiceListResponse:
    """List Stripe invoices for the workspace's customer.

    In mock mode (no STRIPE_SECRET_KEY) returns an empty list — the dev
    workflow shouldn't need invoice data to validate the contract.
    """
    sub = await billing_service.get_subscription(db, current_user.workspace_id)
    if sub is None or sub.stripe_customer_id is None or not stripe_service.enabled:
        return InvoiceListResponse(items=[])

    invoices: list[InvoiceSummary] = []
    try:
        listing = stripe_service.stripe.Invoice.list(  # type: ignore[union-attr]
            customer=sub.stripe_customer_id, limit=20
        )
        for raw in listing.get("data") or []:
            invoices.append(
                InvoiceSummary(
                    id=str(raw.get("id") or ""),
                    amount_cents=int(raw.get("amount_paid") or raw.get("amount_due") or 0),
                    currency=str(raw.get("currency") or "usd").upper(),
                    status=str(raw.get("status") or ""),
                    hosted_invoice_url=raw.get("hosted_invoice_url"),
                    invoice_pdf=raw.get("invoice_pdf"),
                    created_at=(
                        datetime.fromtimestamp(int(raw["created"]), tz=UTC)
                        if raw.get("created")
                        else None
                    ),
                )
            )
    except Exception:  # noqa: BLE001
        return InvoiceListResponse(items=[])

    return InvoiceListResponse(items=invoices)
