"""Reporting endpoints — pipeline, revenue, rep, dashboard, isolation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.dashboard_metric_cache import DashboardMetricCache
from app.models.workspace import Workspace
from tests.helpers import register_workspace

API = "/api/v1"


async def _make_company(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/companies",
        headers=headers,
        json={
            "name": f"Co-{uuid.uuid4().hex[:6]}",
            "domain": f"{uuid.uuid4().hex[:8]}.example.com",
        },
    )
    return resp.json()["id"]


async def _make_contact(
    client: AsyncClient, headers: dict[str, str], company_id: str | None = None
) -> str:
    body: dict[str, object] = {
        "email": f"c-{uuid.uuid4().hex[:6]}@example.com",
        "first_name": "T",
        "last_name": "U",
        "title": "Director",
        "source": "outbound",
    }
    if company_id:
        body["company_id"] = company_id
    resp = await client.post(f"{API}/contacts", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_deal(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    stage_name: str,
    value_cents: int,
    contact_id: str | None = None,
    company_id: str | None = None,
) -> str:
    stages = (await client.get(f"{API}/pipeline-stages", headers=headers)).json()
    stage_id = next(s for s in stages if s["name"] == stage_name)["id"]
    payload: dict[str, object] = {
        "name": f"Deal-{uuid.uuid4().hex[:6]}",
        "pipeline_stage_id": stage_id,
        "value_cents": value_cents,
    }
    if contact_id:
        payload["contact_id"] = contact_id
    if company_id:
        payload["company_id"] = company_id
    resp = await client.post(f"{API}/deals", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _close_deal_won(
    client: AsyncClient, headers: dict[str, str], deal_id: str
) -> None:
    stages = (await client.get(f"{API}/pipeline-stages", headers=headers)).json()
    won = next(s for s in stages if s["name"] == "Closed Won")["id"]
    resp = await client.patch(
        f"{API}/deals/{deal_id}",
        headers=headers,
        json={"pipeline_stage_id": won},
    )
    assert resp.status_code == 200, resp.text


# --- pipeline --------------------------------------------------------------


async def test_pipeline_summary_groups_by_stage(client: AsyncClient) -> None:
    ws = await register_workspace(client, slug_prefix="rpt-pipe")
    company_id = await _make_company(client, ws.headers)
    contact_id = await _make_contact(client, ws.headers, company_id=company_id)

    await _make_deal(
        client, ws.headers, stage_name="Qualified", value_cents=100_000,
        contact_id=contact_id,
    )
    await _make_deal(
        client, ws.headers, stage_name="Qualified", value_cents=200_000,
        contact_id=contact_id,
    )
    await _make_deal(
        client, ws.headers, stage_name="Negotiation", value_cents=500_000,
        contact_id=contact_id,
    )

    resp = await client.get(f"{API}/reports/pipeline", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_pipeline_value_cents"] == 800_000
    assert body["deal_count"] == 3
    assert body["weighted_pipeline_cents"] > 0

    by_stage = {s["stage_name"]: s for s in body["by_stage"]}
    assert by_stage["Qualified"]["deal_count"] == 2
    assert by_stage["Qualified"]["value_cents"] == 300_000
    assert by_stage["Negotiation"]["deal_count"] == 1


async def test_pipeline_summary_owner_filter(client: AsyncClient) -> None:
    ws = await register_workspace(client, slug_prefix="rpt-owner")
    contact_id = await _make_contact(client, ws.headers)
    await _make_deal(
        client, ws.headers, stage_name="Qualified", value_cents=100_000,
        contact_id=contact_id,
    )

    # Filter by a random owner_id returns no deals.
    other_owner = str(uuid.uuid4())
    resp = await client.get(
        f"{API}/reports/pipeline?owner_id={other_owner}", headers=ws.headers
    )
    assert resp.status_code == 200
    assert resp.json()["deal_count"] == 0


# --- revenue ---------------------------------------------------------------


async def test_revenue_by_month(client: AsyncClient) -> None:
    ws = await register_workspace(client, slug_prefix="rpt-rev")
    contact_id = await _make_contact(client, ws.headers)
    deal_id = await _make_deal(
        client, ws.headers, stage_name="Qualified", value_cents=750_000,
        contact_id=contact_id,
    )
    await _close_deal_won(client, ws.headers, deal_id)

    resp = await client.get(f"{API}/reports/revenue/by-month", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows
    this_month = datetime.now(UTC).strftime("%Y-%m")
    match = next((r for r in rows if r["month"] == this_month), None)
    assert match is not None
    assert match["won_deal_count"] == 1
    assert match["won_value_cents"] == 750_000


async def test_revenue_by_source(client: AsyncClient) -> None:
    """Wraps the attribution service; just ensure the endpoint returns a list."""
    ws = await register_workspace(client, slug_prefix="rpt-revsrc")
    resp = await client.get(
        f"{API}/reports/revenue/by-source", headers=ws.headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# --- rep performance -------------------------------------------------------


async def test_rep_performance_includes_registered_admin(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client, slug_prefix="rpt-rep")
    contact_id = await _make_contact(client, ws.headers)
    deal_id = await _make_deal(
        client, ws.headers, stage_name="Qualified", value_cents=400_000,
        contact_id=contact_id,
    )
    await _close_deal_won(client, ws.headers, deal_id)

    resp = await client.get(f"{API}/reports/reps", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) >= 1
    row = rows[0]
    assert {"user_id", "name", "calls_made", "emails_sent",
            "deals_created", "deals_won", "revenue_won_cents",
            "avg_lead_score_owned"} <= set(row.keys())


# --- activity --------------------------------------------------------------


async def test_activity_report_returns_by_type(client: AsyncClient) -> None:
    ws = await register_workspace(client, slug_prefix="rpt-act")
    resp = await client.get(f"{API}/reports/activity", headers=ws.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "by_type" in body
    assert "by_day" in body


# --- leads -----------------------------------------------------------------


async def test_lead_velocity_returns_distribution(client: AsyncClient) -> None:
    ws = await register_workspace(client, slug_prefix="rpt-ld")
    contact_id = await _make_contact(client, ws.headers)
    lead = await client.post(
        f"{API}/leads",
        headers=ws.headers,
        json={"contact_id": contact_id, "source": "inbound"},
    )
    assert lead.status_code == 201, lead.text

    resp = await client.get(f"{API}/reports/leads/velocity", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new_leads"] >= 1
    assert set(body["score_distribution"]) == {"0-25", "26-50", "51-75", "76-100"}


async def test_leads_by_source_groups(client: AsyncClient) -> None:
    ws = await register_workspace(client, slug_prefix="rpt-lds")
    contact_id = await _make_contact(client, ws.headers)
    await client.post(
        f"{API}/leads",
        headers=ws.headers,
        json={"contact_id": contact_id, "source": "outbound"},
    )
    resp = await client.get(f"{API}/reports/leads/by-source", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    sources = {r["source"]: r for r in rows}
    assert "outbound" in sources
    assert sources["outbound"]["lead_count"] >= 1


# --- dashboard -------------------------------------------------------------


async def test_dashboard_endpoint_caches_payload(client: AsyncClient) -> None:
    ws = await register_workspace(client, slug_prefix="rpt-dash")
    contact_id = await _make_contact(client, ws.headers)
    await _make_deal(
        client, ws.headers, stage_name="Qualified", value_cents=250_000,
        contact_id=contact_id,
    )

    resp = await client.get(f"{API}/reports/dashboard", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "pipeline_value_cents",
        "weighted_pipeline_cents",
        "open_deals",
        "leads_this_month",
        "win_rate_90d",
        "avg_deal_size_cents",
        "calls_this_week",
        "emails_sent_this_week",
        "at_risk_deals",
        "top_leads_by_score",
        "cached_at",
    ):
        assert key in body
    assert body["pipeline_value_cents"] == 250_000
    assert body["open_deals"] == 1

    # The cache row exists with a future valid_until.
    async with SessionLocal() as session:
        workspace = (
            await session.execute(
                select(Workspace).where(Workspace.slug == ws.workspace_slug)
            )
        ).scalar_one()
        row = (
            await session.execute(
                select(DashboardMetricCache).where(
                    DashboardMetricCache.workspace_id == workspace.id,
                    DashboardMetricCache.metric_key == "dashboard",
                )
            )
        ).scalar_one()
    assert row.valid_until > datetime.now(UTC) + timedelta(minutes=30)


async def test_dashboard_workspace_isolation(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="dash-a")
    ws_b = await register_workspace(client, slug_prefix="dash-b")
    contact_id = await _make_contact(client, ws_a.headers)
    await _make_deal(
        client, ws_a.headers, stage_name="Qualified", value_cents=999_000,
        contact_id=contact_id,
    )

    a_resp = await client.get(f"{API}/reports/dashboard", headers=ws_a.headers)
    b_resp = await client.get(f"{API}/reports/dashboard", headers=ws_b.headers)
    assert a_resp.status_code == b_resp.status_code == 200
    assert a_resp.json()["pipeline_value_cents"] == 999_000
    assert b_resp.json()["pipeline_value_cents"] == 0


async def test_pipeline_forecast_history_endpoint(client: AsyncClient) -> None:
    ws = await register_workspace(client, slug_prefix="rpt-fhist")
    # Empty workspace — endpoint should still return an empty list.
    resp = await client.get(
        f"{API}/reports/pipeline/history?period=current_month",
        headers=ws.headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_pipeline_velocity_endpoint(client: AsyncClient) -> None:
    ws = await register_workspace(client, slug_prefix="rpt-vel")
    resp = await client.get(
        f"{API}/reports/pipeline/velocity", headers=ws.headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "by_stage" in body
    assert body["window_days"] == 90
