"""Attribution router tests — chains, source/funnel reports, isolation."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.attribution import Attribution
from app.models.workspace import Workspace
from app.routers.tracking import _rate_limiter
from tests.helpers import register_workspace

API = "/api/v1"


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    _rate_limiter.reset()


async def _workspace_token(
    client: AsyncClient, slug_prefix: str = "attr"
) -> tuple[str, str, dict[str, str]]:
    ws = await register_workspace(client, slug_prefix=slug_prefix)
    async with SessionLocal() as session:
        result = await session.execute(
            select(Workspace).where(Workspace.slug == ws.workspace_slug)
        )
        workspace = result.scalar_one()
        return str(workspace.id), workspace.tracking_token or "", ws.headers


async def _track_session_and_form(
    client: AsyncClient,
    token: str,
    *,
    utm_source: str,
    utm_campaign: str | None = None,
    email: str | None = None,
) -> tuple[str, str]:
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    email = email or f"lead-{uuid.uuid4().hex[:6]}@example.com"

    await client.post(
        "/track/session",
        json={
            "session_id": sid,
            "workspace_token": token,
            "url": f"https://x.com/?utm_source={utm_source}",
            "utm_source": utm_source,
            "utm_campaign": utm_campaign,
            "utm_medium": "cpc",
        },
    )
    form_resp = await client.post(
        "/track/form",
        json={
            "session_id": sid,
            "workspace_token": token,
            "form_id": "demo_request",
            "form_data": {"email": email, "first_name": "T"},
        },
    )
    body = form_resp.json()
    return body["contact_id"], body["lead_id"]


async def test_contact_attribution_chain(client: AsyncClient) -> None:
    _, token, headers = await _workspace_token(client)
    contact_id, _ = await _track_session_and_form(
        client, token, utm_source="google_ads", utm_campaign="spring"
    )

    resp = await client.get(
        f"{API}/attribution/contacts/{contact_id}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    chain = resp.json()
    assert len(chain) >= 1
    assert chain[0]["touch_type"] == "first_touch"
    assert chain[0]["source"] == "google_ads"
    assert chain[0]["campaign"] == "spring"


async def test_unknown_contact_returns_404(client: AsyncClient) -> None:
    _, _, headers = await _workspace_token(client)
    fake = str(uuid.uuid4())
    resp = await client.get(f"{API}/attribution/contacts/{fake}", headers=headers)
    assert resp.status_code == 404


async def test_source_report_aggregates_correctly(client: AsyncClient) -> None:
    _, token, headers = await _workspace_token(client)
    # Two google_ads contacts, one facebook_ads.
    await _track_session_and_form(client, token, utm_source="google_ads")
    await _track_session_and_form(client, token, utm_source="google_ads")
    await _track_session_and_form(client, token, utm_source="facebook_ads")

    resp = await client.get(f"{API}/attribution/report/by-source", headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    by_source = {r["source"]: r for r in rows}
    assert by_source["google_ads"]["lead_count"] == 2
    assert by_source["facebook_ads"]["lead_count"] == 1


async def test_campaign_report_groups_by_utm_campaign(client: AsyncClient) -> None:
    _, token, headers = await _workspace_token(client)
    await _track_session_and_form(
        client, token, utm_source="google_ads", utm_campaign="alpha"
    )
    await _track_session_and_form(
        client, token, utm_source="google_ads", utm_campaign="alpha"
    )
    await _track_session_and_form(
        client, token, utm_source="google_ads", utm_campaign="beta"
    )

    resp = await client.get(f"{API}/attribution/report/by-campaign", headers=headers)
    assert resp.status_code == 200, resp.text
    by_campaign = {r["campaign"]: r["lead_count"] for r in resp.json()}
    assert by_campaign.get("alpha") == 2
    assert by_campaign.get("beta") == 1


async def test_funnel_report_returns_counts_and_rates(client: AsyncClient) -> None:
    _, token, headers = await _workspace_token(client)
    await _track_session_and_form(client, token, utm_source="google_ads")
    await _track_session_and_form(client, token, utm_source="google_ads")

    resp = await client.get(f"{API}/attribution/report/funnel", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["sessions"] >= 2
    assert body["leads"] >= 2
    assert "conversion_rates" in body
    rates = body["conversion_rates"]
    assert "pageview_to_session" in rates
    assert "session_to_lead" in rates
    assert "lead_to_deal" in rates
    assert "deal_to_won" in rates


async def test_attribution_backfilled_when_deal_won(client: AsyncClient) -> None:
    _, token, headers = await _workspace_token(client)
    contact_id, _ = await _track_session_and_form(client, token, utm_source="google_ads")

    # Create a deal and move it to Closed Won.
    stages = (await client.get(f"{API}/pipeline-stages", headers=headers)).json()
    qualified = next(s for s in stages if s["name"] == "Qualified")["id"]
    won = next(s for s in stages if s["name"] == "Closed Won")["id"]

    deal_resp = await client.post(
        f"{API}/deals",
        headers=headers,
        json={
            "name": "Won Deal",
            "contact_id": contact_id,
            "pipeline_stage_id": qualified,
            "value_cents": 500_000,
        },
    )
    assert deal_resp.status_code == 201, deal_resp.text
    deal_id = deal_resp.json()["id"]

    won_resp = await client.patch(
        f"{API}/deals/{deal_id}", headers=headers, json={"pipeline_stage_id": won}
    )
    assert won_resp.status_code == 200
    assert won_resp.json()["close_reason"] == "won"

    # Attribution.deal_id must now be backfilled.
    async with SessionLocal() as session:
        result = await session.execute(
            select(Attribution).where(Attribution.contact_id == contact_id)
        )
        rows = list(result.scalars().all())
        assert rows
        assert all(str(r.deal_id) == deal_id for r in rows)

    # Deal report should include this row.
    deal_chain = await client.get(
        f"{API}/attribution/deals/{deal_id}", headers=headers
    )
    assert deal_chain.status_code == 200
    assert len(deal_chain.json()) >= 1

    # by-source report reflects the won deal value.
    src_report = await client.get(
        f"{API}/attribution/report/by-source", headers=headers
    )
    google_row = next(r for r in src_report.json() if r["source"] == "google_ads")
    assert google_row["won_deal_count"] == 1
    assert google_row["won_value_cents"] == 500_000


async def test_workspace_isolation_for_attribution(client: AsyncClient) -> None:
    _, token_a, headers_a = await _workspace_token(client, slug_prefix="iso-a")
    _, _, headers_b = await _workspace_token(client, slug_prefix="iso-b")

    contact_id, _ = await _track_session_and_form(
        client, token_a, utm_source="google_ads"
    )

    # B should not see A's contact attribution.
    resp = await client.get(
        f"{API}/attribution/contacts/{contact_id}", headers=headers_b
    )
    assert resp.status_code == 404


async def test_cac_report(client: AsyncClient) -> None:
    _, token, headers = await _workspace_token(client)
    contact_id, _ = await _track_session_and_form(client, token, utm_source="google_ads")

    # Close a deal.
    stages = (await client.get(f"{API}/pipeline-stages", headers=headers)).json()
    qualified = next(s for s in stages if s["name"] == "Qualified")["id"]
    won = next(s for s in stages if s["name"] == "Closed Won")["id"]
    d = (
        await client.post(
            f"{API}/deals",
            headers=headers,
            json={"name": "D", "contact_id": contact_id, "pipeline_stage_id": qualified},
        )
    ).json()["id"]
    await client.patch(f"{API}/deals/{d}", headers=headers, json={"pipeline_stage_id": won})

    resp = await client.get(
        f"{API}/attribution/report/cac",
        headers=headers,
        params={"ad_spend_cents": 1_000_000},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["source"] == "google_ads" and r["cac_cents"] is not None for r in rows)
