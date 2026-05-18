"""NetSuite config + sync — mocked HTTP, mocked NetSuite responses."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.company import Company
from app.models.deal import Deal
from app.models.netsuite import NetSuiteSyncLog, SyncDirection, SyncStatus
from app.services import netsuite_sync_service
from tests.helpers import register_workspace

API = "/api/v1"


async def _save_config(client: AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.post(
        f"{API}/netsuite/config",
        headers=headers,
        json={
            "account_id": "TSTDRV12345",
            "consumer_key": "ckey",
            "consumer_secret": "csecret",
            "token_id": "tid",
            "token_secret": "tsecret",
            "subsidiary_id": "1",
        },
    )
    assert resp.status_code == 201, resp.text


async def test_save_and_retrieve_config_masks_secrets(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    await _save_config(client, ws.headers)

    resp = await client.get(f"{API}/netsuite/config", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["account_id"] == "TSTDRV12345"
    # Sensitive fields are masked, not blank.
    for field in ("consumer_key", "consumer_secret", "token_id", "token_secret"):
        assert body[field] == "********"


async def test_test_connection_returns_success_in_mock_mode(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    await _save_config(client, ws.headers)

    resp = await client.post(f"{API}/netsuite/test", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["error"] is None


async def test_sync_company_creates_log_and_internal_id(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    await _save_config(client, ws.headers)
    contact_resp = await client.post(
        f"{API}/contacts",
        headers=ws.headers,
        json={"email": f"c-{uuid.uuid4().hex[:6]}@example.com"},
    )
    contact_id = contact_resp.json()["id"]
    company_resp = await client.post(
        f"{API}/companies", headers=ws.headers, json={"name": "BetaCo"}
    )
    company_id = company_resp.json()["id"]
    # Link contact to company so the sync service can find the primary contact.
    await client.patch(
        f"{API}/contacts/{contact_id}",
        headers=ws.headers,
        json={"company_id": company_id},
    )

    resp = await client.post(
        f"{API}/netsuite/sync/company/{company_id}", headers=ws.headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "synced"
    assert body["netsuite_internal_id"] is not None

    async with SessionLocal() as db:
        company = await db.get(Company, uuid.UUID(company_id))
        assert company is not None
        assert company.netsuite_internal_id == body["netsuite_internal_id"]

        log_rows = (
            await db.execute(
                select(NetSuiteSyncLog).where(
                    NetSuiteSyncLog.apex_entity_id == uuid.UUID(company_id)
                )
            )
        ).scalars().all()
        assert any(log.status == SyncStatus.SYNCED for log in log_rows)


async def test_sync_deal_creates_sales_order(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    await _save_config(client, ws.headers)
    company_resp = await client.post(
        f"{API}/companies", headers=ws.headers, json={"name": "GammaCo"}
    )
    company_id = company_resp.json()["id"]
    contact_resp = await client.post(
        f"{API}/contacts",
        headers=ws.headers,
        json={
            "email": f"c-{uuid.uuid4().hex[:6]}@example.com",
            "company_id": company_id,
        },
    )
    contact_id = contact_resp.json()["id"]
    stage_resp = await client.get(f"{API}/pipeline-stages", headers=ws.headers)
    stage_id = next(
        s for s in stage_resp.json() if s["name"] == "Proposal Sent"
    )["id"]
    deal_resp = await client.post(
        f"{API}/deals",
        headers=ws.headers,
        json={
            "name": "Gamma Deal",
            "contact_id": contact_id,
            "company_id": company_id,
            "pipeline_stage_id": stage_id,
            "value_cents": 100_000,
        },
    )
    deal_id = deal_resp.json()["id"]

    resp = await client.post(
        f"{API}/netsuite/sync/deal/{deal_id}", headers=ws.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "synced"

    async with SessionLocal() as db:
        deal = await db.get(Deal, uuid.UUID(deal_id))
        assert deal is not None
        assert deal.netsuite_sales_order_id is not None
        assert deal.netsuite_customer_id is not None


async def test_retry_failed_syncs(client: AsyncClient) -> None:
    """A failed sync log entry should be retried and (in mock mode) succeed."""
    ws = await register_workspace(client)
    await _save_config(client, ws.headers)
    company_resp = await client.post(
        f"{API}/companies", headers=ws.headers, json={"name": "DeltaCo"}
    )
    company_id = company_resp.json()["id"]

    # Seed a failed log manually so we can verify the retry picks it up.
    async with SessionLocal() as db:
        company = await db.get(Company, uuid.UUID(company_id))
        assert company is not None
        log = NetSuiteSyncLog(
            workspace_id=company.workspace_id,
            apex_entity_type="company",
            apex_entity_id=company.id,
            netsuite_record_type="customer",
            sync_direction=SyncDirection.APEX_TO_NETSUITE,
            status=SyncStatus.FAILED,
            error_message="mock failure",
        )
        db.add(log)
        await db.commit()

    resp = await client.post(
        f"{API}/netsuite/sync/retry-failed", headers=ws.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["retried"] >= 1

    async with SessionLocal() as db:
        company = await db.get(Company, uuid.UUID(company_id))
        assert company is not None
        assert company.netsuite_internal_id is not None


async def test_sync_service_uses_mock_when_no_config(client: AsyncClient) -> None:
    """Without a NetSuiteConfig, the sync service still records a log row."""
    ws = await register_workspace(client)
    company_resp = await client.post(
        f"{API}/companies", headers=ws.headers, json={"name": "MockOnly"}
    )
    company_id = company_resp.json()["id"]

    async with SessionLocal() as db:
        company = await db.get(Company, uuid.UUID(company_id))
        assert company is not None
        log = await netsuite_sync_service.sync_company_as_customer(
            db, company.workspace_id, company.id
        )
        await db.commit()
        assert log.status == SyncStatus.SYNCED
        assert log.netsuite_internal_id is not None
