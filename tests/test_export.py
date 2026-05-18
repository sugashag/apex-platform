"""Workspace data export — CSV per entity + ZIP bundle."""

from __future__ import annotations

import io
import uuid
import zipfile

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def test_export_contacts_csv(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    suffix = uuid.uuid4().hex[:6]
    await client.post(
        f"{API}/contacts",
        headers=ws.headers,
        json={
            "email": f"export-{suffix}@example.com",
            "first_name": "Ex",
            "last_name": "Port",
            "lead_score": 11,
        },
    )

    resp = await client.get(f"{API}/export/contacts", headers=ws.headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    text = resp.text
    assert "email" in text.splitlines()[0]
    assert f"export-{suffix}@example.com" in text


async def test_export_deals_csv(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    stages = (
        await client.get(f"{API}/pipeline-stages", headers=ws.headers)
    ).json()
    deal = await client.post(
        f"{API}/deals",
        headers=ws.headers,
        json={
            "name": "Export Deal",
            "pipeline_stage_id": stages[0]["id"],
            "value_cents": 150_000,
        },
    )
    assert deal.status_code == 201, deal.text

    resp = await client.get(f"{API}/export/deals", headers=ws.headers)
    assert resp.status_code == 200
    lines = resp.text.splitlines()
    headers = lines[0].split(",")
    assert "name" in headers
    assert "value_dollars" in headers
    assert any("Export Deal" in line for line in lines[1:])


async def test_export_activities_csv(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    resp = await client.get(f"{API}/export/activities", headers=ws.headers)
    assert resp.status_code == 200
    # Just the header row is fine for a fresh workspace.
    assert resp.text.splitlines()[0].split(",")[0] == "id"


async def test_full_export_returns_zip(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    resp = await client.get(f"{API}/export/full", headers=ws.headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = set(zf.namelist())
    assert {"contacts.csv", "deals.csv", "activities.csv"}.issubset(names)
