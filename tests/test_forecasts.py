"""Pipeline Forecaster — agent writes forecasts, at-risk activities, recommendations."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.activity import Activity, ActivityType, ActorType
from app.models.pipeline_forecast import PipelineForecast
from app.models.workspace import Workspace
from tests.helpers import register_workspace

API = "/api/v1"


async def _seed_pipeline(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[str, str]:
    """Create one company, one contact, one open deal at `Qualified`. Returns
    (deal_id, contact_id)."""
    co = await client.post(
        f"{API}/companies",
        headers=headers,
        json={
            "name": f"Co-{uuid.uuid4().hex[:6]}",
            "domain": f"{uuid.uuid4().hex[:8]}.example.com",
        },
    )
    company_id = co.json()["id"]
    contact = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={
            "email": f"c-{uuid.uuid4().hex[:6]}@example.com",
            "first_name": "Q",
            "last_name": "T",
            "title": "VP",
            "source": "outbound",
            "company_id": company_id,
        },
    )
    contact_id = contact.json()["id"]
    stages = (
        await client.get(f"{API}/pipeline-stages", headers=headers)
    ).json()
    qualified = next(s for s in stages if s["name"] == "Qualified")["id"]
    deal = await client.post(
        f"{API}/deals",
        headers=headers,
        json={
            "name": "Acme Negotiation",
            "contact_id": contact_id,
            "company_id": company_id,
            "pipeline_stage_id": qualified,
            "value_cents": 500_000,
        },
    )
    assert deal.status_code == 201, deal.text
    return deal.json()["id"], contact_id


async def _workspace_id(client: AsyncClient, slug: str) -> uuid.UUID:
    async with SessionLocal() as session:
        ws = (
            await session.execute(select(Workspace).where(Workspace.slug == slug))
        ).scalar_one()
        return ws.id


async def test_generate_forecast_writes_two_forecast_rows(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client, slug_prefix="fcast")
    await _seed_pipeline(client, ws.headers)

    resp = await client.post(
        f"{API}/forecasts/generate", headers=ws.headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert len(body["forecasts"]) == 2
    periods = {f["forecast_period"] for f in body["forecasts"]}
    assert periods == {"current_month", "next_month"}

    workspace_id = await _workspace_id(client, ws.workspace_slug)
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(PipelineForecast).where(
                    PipelineForecast.workspace_id == workspace_id
                )
            )
        ).scalars().all()
    assert len(rows) == 2
    for r in rows:
        assert r.deal_count >= 1
        assert r.pipeline_value_cents >= 500_000
        assert r.agent_run_id is not None


async def test_generate_forecast_creates_at_risk_activities(
    client: AsyncClient,
    monkeypatch,
) -> None:
    """When Claude flags a deal as at-risk, an Activity is created on that deal."""
    ws = await register_workspace(client, slug_prefix="fcrisk")
    deal_id, _ = await _seed_pipeline(client, ws.headers)

    import app.services.anthropic_service as svc

    async def fake_complete(*args, **kwargs):  # type: ignore[no-untyped-def]
        import json as _json

        payload = {
            "forecast_current_month_cents": 1_000_000,
            "forecast_next_month_cents": 2_000_000,
            "confidence": "medium",
            "at_risk_deals": [
                {
                    "deal_id": deal_id,
                    "deal_name": "Acme Negotiation",
                    "risk_reason": "No activity in 14 days, expected close in 3 days",
                    "recommended_action": "Call today and offer to extend timeline",
                }
            ],
            "recommendations": [
                "Focus on the 1 deal in Qualified worth $5K",
            ],
            "pipeline_health": "below_target",
        }
        return _json.dumps(payload), 100, 200

    monkeypatch.setattr(svc.anthropic_service, "complete", fake_complete)

    resp = await client.post(
        f"{API}/forecasts/generate", headers=ws.headers
    )
    assert resp.status_code == 201, resp.text

    workspace_id = await _workspace_id(client, ws.workspace_slug)
    async with SessionLocal() as session:
        forecasts = (
            await session.execute(
                select(PipelineForecast).where(
                    PipelineForecast.workspace_id == workspace_id
                )
            )
        ).scalars().all()
        assert all(
            uuid.UUID(deal_id) in {uuid.UUID(x) for x in (f.at_risk_deal_ids or [])}
            for f in forecasts
        )

        activities = (
            await session.execute(
                select(Activity).where(
                    Activity.deal_id == uuid.UUID(deal_id),
                    Activity.actor_type == ActorType.AI_AGENT,
                    Activity.type == ActivityType.NOTE,
                )
            )
        ).scalars().all()
        # One Activity per at-risk deal (deduped across the two forecast periods).
        assert len(activities) == 1
        assert "No activity in 14 days" in (activities[0].body or "")
        assert "Call today" in (activities[0].body or "")


async def test_latest_forecast_endpoint(client: AsyncClient) -> None:
    ws = await register_workspace(client, slug_prefix="fcget")
    await _seed_pipeline(client, ws.headers)
    await client.post(f"{API}/forecasts/generate", headers=ws.headers)

    resp = await client.get(
        f"{API}/forecasts/latest?period=current_month", headers=ws.headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body is not None
    assert body["forecast_period"] == "current_month"
    assert "forecast_value_cents" in body


async def test_forecasts_list_workspace_isolation(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="fc-iso-a")
    ws_b = await register_workspace(client, slug_prefix="fc-iso-b")
    await _seed_pipeline(client, ws_a.headers)
    await client.post(f"{API}/forecasts/generate", headers=ws_a.headers)

    # B sees no forecasts.
    resp = await client.get(f"{API}/forecasts", headers=ws_b.headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_forecast_invalidates_dashboard_cache(
    client: AsyncClient,
) -> None:
    """After the forecaster runs, the dashboard read should reflect new at-risk ids."""
    ws = await register_workspace(client, slug_prefix="fcdash")
    deal_id, _ = await _seed_pipeline(client, ws.headers)

    # Prime the cache.
    first = await client.get(f"{API}/reports/dashboard", headers=ws.headers)
    assert first.status_code == 200

    import app.services.anthropic_service as svc

    async def fake_complete(*args, **kwargs):  # type: ignore[no-untyped-def]
        import json as _json

        return _json.dumps(
            {
                "forecast_current_month_cents": 1,
                "forecast_next_month_cents": 2,
                "confidence": "low",
                "at_risk_deals": [
                    {
                        "deal_id": deal_id,
                        "deal_name": "Acme Negotiation",
                        "risk_reason": "stalled",
                        "recommended_action": "call",
                    }
                ],
                "recommendations": [],
                "pipeline_health": "critical",
            }
        ), 10, 10

    from pytest import MonkeyPatch

    mp = MonkeyPatch()
    try:
        mp.setattr(svc.anthropic_service, "complete", fake_complete)
        gen = await client.post(f"{API}/forecasts/generate", headers=ws.headers)
        assert gen.status_code == 201, gen.text
    finally:
        mp.undo()

    second = await client.get(f"{API}/reports/dashboard", headers=ws.headers)
    assert second.status_code == 200
    payload = second.json()
    assert deal_id in payload["at_risk_deals"]
