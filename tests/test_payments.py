"""Payments — manual creation, intent flow, list/filter, deal-scoped lookup."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def _new_contact(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={"email": f"c-{uuid.uuid4().hex[:6]}@example.com"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _stage_id(
    client: AsyncClient, headers: dict[str, str], name: str
) -> str:
    resp = await client.get(f"{API}/pipeline-stages", headers=headers)
    return next(s for s in resp.json() if s["name"] == name)["id"]


async def _new_deal(client: AsyncClient, headers: dict[str, str]) -> str:
    contact_id = await _new_contact(client, headers)
    stage_id = await _stage_id(client, headers, "Qualified")
    resp = await client.post(
        f"{API}/deals",
        headers=headers,
        json={
            "name": "Deal A",
            "contact_id": contact_id,
            "pipeline_stage_id": stage_id,
            "value_cents": 500_000,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_create_payment_manual(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    deal_id = await _new_deal(client, ws.headers)

    resp = await client.post(
        f"{API}/payments",
        headers=ws.headers,
        json={
            "deal_id": deal_id,
            "amount_cents": 100_000,
            "currency": "USD",
            "description": "Deposit",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["amount_cents"] == 100_000
    assert body["status"] == "pending"
    assert body["currency"] == "USD"


async def test_create_payment_intent_uses_mock_stripe(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    deal_id = await _new_deal(client, ws.headers)

    resp = await client.post(
        f"{API}/payments/create-intent",
        headers=ws.headers,
        json={"deal_id": deal_id, "amount_cents": 250_000, "currency": "USD"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["amount_cents"] == 250_000
    assert body["payment_intent_id"].startswith("pi_")
    assert "secret" in body["client_secret"]

    # The mock intent should have created a pending Payment row.
    list_resp = await client.get(
        f"{API}/payments",
        headers=ws.headers,
        params={"deal_id": deal_id},
    )
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["stripe_payment_intent_id"] == body["payment_intent_id"]
    assert items[0]["status"] == "pending"


async def test_list_payments_filters_by_status(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    deal_id = await _new_deal(client, ws.headers)

    for amount, status_val in (
        (10_000, "pending"),
        (20_000, "succeeded"),
        (30_000, "failed"),
    ):
        resp = await client.post(
            f"{API}/payments",
            headers=ws.headers,
            json={
                "deal_id": deal_id,
                "amount_cents": amount,
                "status": status_val,
            },
        )
        assert resp.status_code == 201, resp.text

    resp = await client.get(
        f"{API}/payments",
        headers=ws.headers,
        params={"status": "succeeded"},
    )
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["amount_cents"] == 20_000


async def test_deal_scoped_payments(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    deal_id = await _new_deal(client, ws.headers)
    other_deal_id = await _new_deal(client, ws.headers)

    await client.post(
        f"{API}/payments",
        headers=ws.headers,
        json={"deal_id": deal_id, "amount_cents": 1_000},
    )
    await client.post(
        f"{API}/payments",
        headers=ws.headers,
        json={"deal_id": other_deal_id, "amount_cents": 2_000},
    )

    resp = await client.get(
        f"{API}/deals/{deal_id}/payments", headers=ws.headers
    )
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["amount_cents"] == 1_000
