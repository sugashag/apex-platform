"""LeadScoreHistory — history row written on score, trend endpoint exposes it."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.lead_score_history import LeadScoreHistory
from tests.helpers import register_workspace

API = "/api/v1"


async def _new_lead(client: AsyncClient, headers: dict[str, str]) -> str:
    company = await client.post(
        f"{API}/companies",
        headers=headers,
        json={
            "name": f"Co-{uuid.uuid4().hex[:6]}",
            "domain": f"{uuid.uuid4().hex[:8]}.example.com",
        },
    )
    company_id = company.json()["id"]
    contact = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={
            "email": f"c-{uuid.uuid4().hex[:6]}@example.com",
            "first_name": "P",
            "last_name": "S",
            "title": "VP",
            "source": "inbound",
            "company_id": company_id,
        },
    )
    contact_id = contact.json()["id"]
    lead = await client.post(
        f"{API}/leads",
        headers=headers,
        json={"contact_id": contact_id, "source": "inbound"},
    )
    return lead.json()["id"]


async def test_history_row_inserted_when_lead_scorer_runs(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client, slug_prefix="lsh")
    lead_id = await _new_lead(client, ws.headers)

    score_resp = await client.post(
        f"{API}/agents/leads/{lead_id}/score", headers=ws.headers
    )
    assert score_resp.status_code == 201, score_resp.text

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(LeadScoreHistory).where(
                    LeadScoreHistory.lead_id == uuid.UUID(lead_id)
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert 0 <= row.score <= 100
    assert row.score_rationale
    assert row.agent_run_id is not None


async def test_score_trend_endpoint_returns_history(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client, slug_prefix="trend")
    lead_id = await _new_lead(client, ws.headers)

    # Score the lead twice — two history rows expected.
    for _ in range(2):
        resp = await client.post(
            f"{API}/agents/leads/{lead_id}/score", headers=ws.headers
        )
        assert resp.status_code == 201

    trend = await client.get(
        f"{API}/reports/leads/{lead_id}/score-trend", headers=ws.headers
    )
    assert trend.status_code == 200, trend.text
    items = trend.json()
    assert len(items) >= 2
    for item in items:
        assert "scored_at" in item
        assert "score" in item
        assert "rationale" in item


async def test_score_trend_404_for_other_workspace(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="trend-a")
    ws_b = await register_workspace(client, slug_prefix="trend-b")
    lead_id = await _new_lead(client, ws_a.headers)

    resp = await client.get(
        f"{API}/reports/leads/{lead_id}/score-trend", headers=ws_b.headers
    )
    assert resp.status_code == 404
