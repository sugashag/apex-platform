"""MSA generation, send-for-signing, and confirm-signed flows."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.deal import CloseReason, Deal
from app.models.pipeline_stage import PipelineStage
from tests.helpers import register_workspace

API = "/api/v1"


async def _new_contact(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={
            "email": f"c-{uuid.uuid4().hex[:6]}@example.com",
            "first_name": "Pat",
            "last_name": "Tester",
        },
    )
    return resp.json()["id"]


async def _stage_id(
    client: AsyncClient, headers: dict[str, str], name: str
) -> str:
    resp = await client.get(f"{API}/pipeline-stages", headers=headers)
    return next(s for s in resp.json() if s["name"] == name)["id"]


async def _new_deal(client: AsyncClient, headers: dict[str, str]) -> str:
    contact_id = await _new_contact(client, headers)
    company_resp = await client.post(
        f"{API}/companies", headers=headers, json={"name": "AcmeCo"}
    )
    company_id = company_resp.json()["id"]
    stage_id = await _stage_id(client, headers, "Proposal Sent")
    resp = await client.post(
        f"{API}/deals",
        headers=headers,
        json={
            "name": "Deal MSA",
            "contact_id": contact_id,
            "company_id": company_id,
            "pipeline_stage_id": stage_id,
            "value_cents": 750_000,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_generate_msa_creates_document_and_activity(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    deal_id = await _new_deal(client, ws.headers)

    resp = await client.post(
        f"{API}/msa/generate",
        headers=ws.headers,
        json={"deal_id": deal_id},
    )
    assert resp.status_code == 201, resp.text
    msa = resp.json()
    assert msa["status"] == "draft"
    assert msa["document_url"] is not None
    assert msa["deal_id"] == deal_id

    detail = await client.get(f"{API}/deals/{deal_id}", headers=ws.headers)
    assert any(
        a["subject"] == "MSA generated"
        for a in detail.json()["recent_activities"]
    )


async def test_send_for_signing(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    deal_id = await _new_deal(client, ws.headers)
    gen = await client.post(
        f"{API}/msa/generate", headers=ws.headers, json={"deal_id": deal_id}
    )
    msa_id = gen.json()["id"]

    send = await client.post(
        f"{API}/msa/{msa_id}/send",
        headers=ws.headers,
        json={"signer_email": "buyer@acme.example", "signer_name": "Buyer Person"},
    )
    assert send.status_code == 200, send.text
    body = send.json()
    assert body["status"] == "sent"
    assert body["signer_email"] == "buyer@acme.example"
    assert body["signing_url"] is not None
    assert body["sent_at"] is not None


async def test_confirm_signed_moves_deal_to_closed_won(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    deal_id = await _new_deal(client, ws.headers)
    gen = await client.post(
        f"{API}/msa/generate", headers=ws.headers, json={"deal_id": deal_id}
    )
    msa_id = gen.json()["id"]
    await client.post(
        f"{API}/msa/{msa_id}/send",
        headers=ws.headers,
        json={"signer_email": "x@y.example", "signer_name": "X Y"},
    )

    confirm = await client.post(
        f"{API}/msa/{msa_id}/confirm-signed",
        headers=ws.headers,
        json={},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "signed"
    assert confirm.json()["signed_at"] is not None

    async with SessionLocal() as db:
        deal = await db.get(Deal, uuid.UUID(deal_id))
        assert deal is not None
        assert deal.msa_signed_at is not None
        assert deal.close_reason == CloseReason.WON
        # Should be on the Closed Won stage.
        stage = (
            await db.execute(
                select(PipelineStage).where(
                    PipelineStage.id == deal.pipeline_stage_id
                )
            )
        ).scalar_one()
        assert stage.is_won is True


async def test_deal_scoped_msa_lookup(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    deal_id = await _new_deal(client, ws.headers)

    # No MSA yet.
    none_resp = await client.get(
        f"{API}/deals/{deal_id}/msa", headers=ws.headers
    )
    assert none_resp.status_code == 200
    assert none_resp.json() is None

    gen = await client.post(
        f"{API}/msa/generate", headers=ws.headers, json={"deal_id": deal_id}
    )
    expected_id = gen.json()["id"]

    found = await client.get(
        f"{API}/deals/{deal_id}/msa", headers=ws.headers
    )
    assert found.status_code == 200
    assert found.json()["id"] == expected_id
