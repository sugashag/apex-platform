"""Billing service — APEX's own Stripe subscription management.

This is *not* the customer-deal payment flow (that lives in
``stripe_service`` + ``payments`` router). This service handles APEX's
plan-level subscriptions: a workspace pays APEX so it can use the product.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Plan
from app.models.workspace import Workspace
from app.models.workspace_subscription import (
    SubscriptionStatus,
    WorkspaceSubscription,
)
from app.services.stripe_service import stripe_service

logger = logging.getLogger(__name__)

TRIAL_LENGTH_DAYS = 14
STARTER_PLAN_SLUG = "starter"


async def _get_plan(db: AsyncSession, plan_id: UUID) -> Plan | None:
    return await db.get(Plan, plan_id)


async def get_plan_by_slug(db: AsyncSession, slug: str) -> Plan | None:
    result = await db.execute(select(Plan).where(Plan.slug == slug))
    return result.scalar_one_or_none()


async def get_subscription(
    db: AsyncSession, workspace_id: UUID
) -> WorkspaceSubscription | None:
    """Return the workspace's subscription (or None if not yet created)."""
    result = await db.execute(
        select(WorkspaceSubscription).where(
            WorkspaceSubscription.workspace_id == workspace_id
        )
    )
    return result.scalar_one_or_none()


async def start_trial_subscription(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    plan: Plan,
    billing_email: str | None = None,
    billing_name: str | None = None,
) -> WorkspaceSubscription:
    """Create a trial subscription with no Stripe customer yet.

    Used at registration time so every new workspace starts with a row in
    ``workspace_subscriptions``. The Stripe customer is created later when
    the user actually subscribes via ``create_subscription``.
    """
    now = datetime.now(tz=UTC)
    subscription = WorkspaceSubscription(
        workspace_id=workspace_id,
        plan_id=plan.id,
        status=SubscriptionStatus.TRIALING,
        trial_ends_at=now + timedelta(days=TRIAL_LENGTH_DAYS),
        billing_email=billing_email,
        billing_name=billing_name,
    )
    db.add(subscription)
    await db.flush()
    return subscription


async def create_subscription(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    plan_id: UUID,
    billing_email: str,
    billing_name: str,
) -> WorkspaceSubscription:
    """Create (or replace) a workspace subscription and Stripe customer.

    Starts a 14-day trial. When the Stripe SDK isn't configured this returns
    a record with mock customer/subscription identifiers — useful in dev.
    """
    plan = await _get_plan(db, plan_id)
    if plan is None:
        raise ValueError("plan not found")

    workspace = await db.get(Workspace, workspace_id)
    workspace_name = workspace.name if workspace is not None else None

    metadata: dict[str, str] = {"workspace_id": str(workspace_id)}
    if workspace_name:
        metadata["workspace_name"] = workspace_name

    customer_id = await stripe_service.create_customer(
        email=billing_email,
        name=billing_name,
        metadata=metadata,
    )

    now = datetime.now(tz=UTC)
    subscription = await get_subscription(db, workspace_id)
    if subscription is None:
        subscription = WorkspaceSubscription(workspace_id=workspace_id, plan_id=plan_id)
        db.add(subscription)

    subscription.plan_id = plan_id
    subscription.stripe_customer_id = customer_id
    subscription.stripe_subscription_id = (
        subscription.stripe_subscription_id or f"sub_mock_{customer_id[-12:]}"
    )
    subscription.status = SubscriptionStatus.TRIALING
    subscription.trial_ends_at = now + timedelta(days=TRIAL_LENGTH_DAYS)
    subscription.current_period_start = now
    subscription.current_period_end = now + timedelta(days=TRIAL_LENGTH_DAYS)
    subscription.cancelled_at = None
    subscription.billing_email = billing_email
    subscription.billing_name = billing_name

    await db.flush()
    return subscription


async def cancel_subscription(
    db: AsyncSession, workspace_id: UUID
) -> WorkspaceSubscription:
    """Mark a subscription cancelled. Stripe would handle cancel-at-period-end."""
    subscription = await get_subscription(db, workspace_id)
    if subscription is None:
        raise ValueError("workspace has no subscription")
    subscription.status = SubscriptionStatus.CANCELLED
    subscription.cancelled_at = datetime.now(tz=UTC)
    await db.flush()
    return subscription


def _epoch_to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError):
        return None


async def handle_subscription_event(
    db: AsyncSession,
    event_type: str,
    stripe_data: dict[str, Any],
) -> WorkspaceSubscription | None:
    """Update a WorkspaceSubscription in response to a Stripe billing event.

    ``stripe_data`` is the inner ``event["data"]["object"]`` dict. Returns the
    updated subscription, or ``None`` if no matching workspace was found.
    """
    customer_id = stripe_data.get("customer")
    subscription_id = stripe_data.get("id") or stripe_data.get("subscription")

    subscription: WorkspaceSubscription | None = None
    if isinstance(subscription_id, str):
        result = await db.execute(
            select(WorkspaceSubscription).where(
                WorkspaceSubscription.stripe_subscription_id == subscription_id
            )
        )
        subscription = result.scalar_one_or_none()

    if subscription is None and isinstance(customer_id, str):
        result = await db.execute(
            select(WorkspaceSubscription).where(
                WorkspaceSubscription.stripe_customer_id == customer_id
            )
        )
        subscription = result.scalar_one_or_none()

    if subscription is None:
        logger.info(
            "billing webhook %s could not be matched to a workspace (customer=%s sub=%s)",
            event_type, customer_id, subscription_id,
        )
        return None

    if event_type == "customer.subscription.updated":
        status_raw = stripe_data.get("status")
        if isinstance(status_raw, str):
            try:
                subscription.status = SubscriptionStatus(status_raw)
            except ValueError:
                pass
        subscription.current_period_start = (
            _epoch_to_dt(stripe_data.get("current_period_start"))
            or subscription.current_period_start
        )
        subscription.current_period_end = (
            _epoch_to_dt(stripe_data.get("current_period_end"))
            or subscription.current_period_end
        )
        if isinstance(subscription_id, str):
            subscription.stripe_subscription_id = subscription_id

    elif event_type == "customer.subscription.deleted":
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = datetime.now(tz=UTC)

    elif event_type == "invoice.payment_failed":
        subscription.status = SubscriptionStatus.PAST_DUE

    elif event_type == "invoice.paid":
        subscription.status = SubscriptionStatus.ACTIVE
        period_start = _epoch_to_dt(stripe_data.get("period_start"))
        period_end = _epoch_to_dt(stripe_data.get("period_end"))
        if period_start is not None:
            subscription.current_period_start = period_start
        if period_end is not None:
            subscription.current_period_end = period_end

    await db.flush()
    return subscription


def is_billing_subscription_event(event_type: str, stripe_data: dict[str, Any]) -> bool:
    """True if a Stripe event is APEX-platform billing (vs customer-deal payments).

    We distinguish by:
    - ``customer.subscription.*`` and ``invoice.payment_failed`` are always billing.
    - ``invoice.paid`` is billing only when the invoice metadata flags it
      (``apex_billing=true``) or there's a matching ``workspace_subscriptions``
      row keyed by customer/subscription id. The caller verifies the match;
      this helper just gates the event-type whitelist.
    """
    if event_type in {
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_failed",
    }:
        return True
    if event_type == "invoice.paid":
        metadata = stripe_data.get("metadata") or {}
        if isinstance(metadata, dict) and str(metadata.get("apex_billing", "")).lower() == "true":
            return True
    return False


__all__ = [
    "STARTER_PLAN_SLUG",
    "TRIAL_LENGTH_DAYS",
    "cancel_subscription",
    "create_subscription",
    "get_plan_by_slug",
    "get_subscription",
    "handle_subscription_event",
    "is_billing_subscription_event",
    "start_trial_subscription",
]
