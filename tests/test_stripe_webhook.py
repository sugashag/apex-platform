"""Stripe webhook handler — full event processing with mocked signature validation."""

from __future__ import annotations

import json
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.deal import Deal
from app.models.payment import Payment, PaymentStatus
from tests.helpers import register_workspace

API = "/api/v1"


async def _new_contact(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={"email": f"c-{uuid.uuid4().hex[:6]}@example.com"},
    )
    return resp.json()["id"]


async def _stage_id(
    client: AsyncClient, headers: dict[str, str], name: str
) -> str:
    resp = await client.get(f"{API}/pipeline-stages", headers=headers)
    return next(s for s in resp.json() if s["name"] == name)["id"]


async def _new_deal_with_payment_intent(
    client: AsyncClient, headers: dict[str, str], amount: int = 100_000
) -> tuple[str, str]:
    contact_id = await _new_contact(client, headers)
    stage_id = await _stage_id(client, headers, "Qualified")
    deal_resp = await client.post(
        f"{API}/deals",
        headers=headers,
        json={
            "name": "Webhook deal",
            "contact_id": contact_id,
            "pipeline_stage_id": stage_id,
            "value_cents": amount,
        },
    )
    deal_id = deal_resp.json()["id"]
    intent_resp = await client.post(
        f"{API}/payments/create-intent",
        headers=headers,
        json={"deal_id": deal_id, "amount_cents": amount, "currency": "USD"},
    )
    return deal_id, intent_resp.json()["payment_intent_id"]


def _event(event_type: str, obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": event_type,
        "created": 1_700_000_000,
        "data": {"object": obj},
    }


async def test_payment_intent_succeeded_marks_first_payment(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    deal_id, intent_id = await _new_deal_with_payment_intent(client, ws.headers)

    payload = _event(
        "payment_intent.succeeded",
        {
            "id": intent_id,
            "amount": 100_000,
            "amount_received": 100_000,
            "currency": "usd",
            "customer": "cus_test",
            "metadata": {"workspace_id": "ignored", "deal_id": deal_id},
        },
    )
    resp = await client.post(
        "/webhooks/stripe", content=json.dumps(payload).encode("utf-8")
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["event"] == "payment_intent.succeeded"

    async with SessionLocal() as db:
        result = await db.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
        )
        payment = result.scalar_one()
        assert payment.status == PaymentStatus.SUCCEEDED
        assert payment.is_first_payment is True
        assert payment.paid_at is not None

        deal = await db.get(Deal, uuid.UUID(deal_id))
        assert deal is not None and deal.first_payment_at is not None


async def test_second_payment_is_not_first(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    deal_id, first_intent = await _new_deal_with_payment_intent(client, ws.headers)

    # Second intent on the SAME deal.
    second_resp = await client.post(
        f"{API}/payments/create-intent",
        headers=ws.headers,
        json={"deal_id": deal_id, "amount_cents": 50_000, "currency": "USD"},
    )
    second_intent = second_resp.json()["payment_intent_id"]

    for intent_id in (first_intent, second_intent):
        payload = _event(
            "payment_intent.succeeded",
            {
                "id": intent_id,
                "amount": 100_000,
                "amount_received": 100_000,
                "currency": "usd",
                "metadata": {"deal_id": deal_id},
            },
        )
        resp = await client.post(
            "/webhooks/stripe", content=json.dumps(payload).encode("utf-8")
        )
        assert resp.status_code == 200, resp.text

    async with SessionLocal() as db:
        first = (
            await db.execute(
                select(Payment).where(
                    Payment.stripe_payment_intent_id == first_intent
                )
            )
        ).scalar_one()
        second = (
            await db.execute(
                select(Payment).where(
                    Payment.stripe_payment_intent_id == second_intent
                )
            )
        ).scalar_one()
        assert first.is_first_payment is True
        assert second.is_first_payment is False


async def test_payment_intent_failed_records_failure(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    _, intent_id = await _new_deal_with_payment_intent(client, ws.headers)

    payload = _event(
        "payment_intent.payment_failed",
        {
            "id": intent_id,
            "last_payment_error": {"message": "card declined"},
            "metadata": {},
        },
    )
    resp = await client.post(
        "/webhooks/stripe", content=json.dumps(payload).encode("utf-8")
    )
    assert resp.status_code == 200

    async with SessionLocal() as db:
        payment = (
            await db.execute(
                select(Payment).where(
                    Payment.stripe_payment_intent_id == intent_id
                )
            )
        ).scalar_one()
        assert payment.status == PaymentStatus.FAILED


async def test_unknown_event_type_is_ignored(client: AsyncClient) -> None:
    payload = _event(
        "checkout.session.expired",
        {"id": "cs_test"},
    )
    resp = await client.post(
        "/webhooks/stripe", content=json.dumps(payload).encode("utf-8")
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
