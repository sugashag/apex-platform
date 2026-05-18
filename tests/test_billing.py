"""Billing routes — plan catalog, subscribe, cancel, webhook handling."""

from __future__ import annotations

import json
import uuid

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def test_list_plans_public(client: AsyncClient) -> None:
    resp = await client.get(f"{API}/billing/plans")
    assert resp.status_code == 200
    plans = resp.json()
    slugs = {p["slug"] for p in plans}
    assert {"starter", "growth", "enterprise"}.issubset(slugs)
    starter = next(p for p in plans if p["slug"] == "starter")
    assert starter["price_cents_monthly"] == 7500
    assert starter["includes_netsuite"] is False
    growth = next(p for p in plans if p["slug"] == "growth")
    assert growth["includes_netsuite"] is True


async def test_registration_creates_trial_subscription(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    resp = await client.get(f"{API}/billing/subscription", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    sub = resp.json()
    assert sub["status"] == "trialing"
    assert sub["trial_ends_at"] is not None
    assert sub["plan"] is not None
    assert sub["plan"]["slug"] == "starter"


async def test_subscribe_replaces_plan(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    plans = (await client.get(f"{API}/billing/plans")).json()
    growth = next(p for p in plans if p["slug"] == "growth")

    resp = await client.post(
        f"{API}/billing/subscribe",
        headers=ws.headers,
        json={
            "plan_id": growth["id"],
            "billing_email": "billing@example.com",
            "billing_name": "ACME Corp",
        },
    )
    assert resp.status_code == 201, resp.text
    sub = resp.json()
    assert sub["plan"]["slug"] == "growth"
    assert sub["billing_email"] == "billing@example.com"
    assert sub["stripe_customer_id"] is not None
    assert sub["status"] == "trialing"


async def test_cancel_marks_cancelled(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    resp = await client.post(f"{API}/billing/cancel", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"
    assert resp.json()["cancelled_at"] is not None


async def test_invoice_payment_failed_marks_past_due(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    # Subscribe so we have a stripe_customer_id to key on.
    plans = (await client.get(f"{API}/billing/plans")).json()
    starter = next(p for p in plans if p["slug"] == "starter")
    sub = (
        await client.post(
            f"{API}/billing/subscribe",
            headers=ws.headers,
            json={
                "plan_id": starter["id"],
                "billing_email": "pay@example.com",
                "billing_name": "Test",
            },
        )
    ).json()
    customer_id = sub["stripe_customer_id"]

    event = {
        "type": "invoice.payment_failed",
        "created": 1_700_000_000,
        "data": {
            "object": {
                "id": f"in_{uuid.uuid4().hex}",
                "customer": customer_id,
                "metadata": {"apex_billing": "true"},
            }
        },
    }
    resp = await client.post(
        "/webhooks/stripe",
        content=json.dumps(event),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 200, resp.text

    after = (await client.get(f"{API}/billing/subscription", headers=ws.headers)).json()
    assert after["status"] == "past_due"


async def test_invoice_paid_marks_active(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    plans = (await client.get(f"{API}/billing/plans")).json()
    starter = next(p for p in plans if p["slug"] == "starter")
    sub = (
        await client.post(
            f"{API}/billing/subscribe",
            headers=ws.headers,
            json={
                "plan_id": starter["id"],
                "billing_email": "active@example.com",
                "billing_name": "Test",
            },
        )
    ).json()
    customer_id = sub["stripe_customer_id"]

    event = {
        "type": "invoice.paid",
        "created": 1_700_000_500,
        "data": {
            "object": {
                "id": f"in_{uuid.uuid4().hex}",
                "customer": customer_id,
                "amount_paid": 8500,
                "currency": "usd",
                "metadata": {"apex_billing": "true"},
                "period_start": 1_700_000_000,
                "period_end": 1_700_500_000,
            }
        },
    }
    resp = await client.post(
        "/webhooks/stripe",
        content=json.dumps(event),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 200, resp.text

    after = (await client.get(f"{API}/billing/subscription", headers=ws.headers)).json()
    assert after["status"] == "active"
