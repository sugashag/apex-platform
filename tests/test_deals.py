"""Deal CRUD, stage-change activity, lead conversion, workspace isolation."""

import uuid

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def _new_email() -> str:
    return f"contact-{uuid.uuid4().hex[:6]}@example.com"


async def _stage_id_by_name(
    client: AsyncClient, headers: dict[str, str], name: str,
) -> str:
    resp = await client.get(f"{API}/pipeline-stages", headers=headers)
    return next(s for s in resp.json() if s["name"] == name)["id"]


async def test_create_deal_records_stage_change_activity(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)

    contact_resp = await client.post(
        f"{API}/contacts", headers=ws.headers,
        json={"email": await _new_email()},
    )
    contact_id = contact_resp.json()["id"]
    stage_id = await _stage_id_by_name(client, ws.headers, "Qualified")

    deal_resp = await client.post(
        f"{API}/deals",
        headers=ws.headers,
        json={
            "name": "Big Deal",
            "contact_id": contact_id,
            "pipeline_stage_id": stage_id,
            "value_cents": 1_000_000,
        },
    )
    assert deal_resp.status_code == 201, deal_resp.text
    deal_id = deal_resp.json()["id"]
    assert deal_resp.json()["probability"] == 30  # Qualified default

    # GET should include the stage_change activity.
    detail = await client.get(f"{API}/deals/{deal_id}", headers=ws.headers)
    assert detail.status_code == 200
    activities = detail.json()["recent_activities"]
    assert any(a["type"] == "stage_change" for a in activities)


async def test_stage_change_via_patch_creates_activity(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    qualified = await _stage_id_by_name(client, ws.headers, "Qualified")
    proposal = await _stage_id_by_name(client, ws.headers, "Proposal Sent")
    won = await _stage_id_by_name(client, ws.headers, "Closed Won")

    deal_resp = await client.post(
        f"{API}/deals",
        headers=ws.headers,
        json={"name": "D1", "pipeline_stage_id": qualified},
    )
    deal_id = deal_resp.json()["id"]

    patched = await client.patch(
        f"{API}/deals/{deal_id}",
        headers=ws.headers,
        json={"pipeline_stage_id": proposal},
    )
    assert patched.status_code == 200
    assert patched.json()["pipeline_stage_id"] == proposal

    # Move to won — should set closed_at + close_reason.
    won_patch = await client.patch(
        f"{API}/deals/{deal_id}",
        headers=ws.headers,
        json={"pipeline_stage_id": won},
    )
    assert won_patch.status_code == 200
    assert won_patch.json()["close_reason"] == "won"
    assert won_patch.json()["closed_at"] is not None

    detail = await client.get(f"{API}/deals/{deal_id}", headers=ws.headers)
    stage_changes = [
        a for a in detail.json()["recent_activities"] if a["type"] == "stage_change"
    ]
    assert len(stage_changes) >= 3


async def test_lead_conversion_creates_deal_and_links(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)

    contact_resp = await client.post(
        f"{API}/contacts", headers=ws.headers,
        json={"email": await _new_email()},
    )
    contact_id = contact_resp.json()["id"]

    lead_resp = await client.post(
        f"{API}/leads",
        headers=ws.headers,
        json={"contact_id": contact_id, "source": "google_ads"},
    )
    assert lead_resp.status_code == 201
    lead_id = lead_resp.json()["id"]

    proposal = await _stage_id_by_name(client, ws.headers, "Proposal Sent")
    convert = await client.post(
        f"{API}/leads/{lead_id}/convert",
        headers=ws.headers,
        json={
            "name": "Converted Deal",
            "pipeline_stage_id": proposal,
            "value_cents": 250_000,
        },
    )
    assert convert.status_code == 201, convert.text
    deal_id = convert.json()["id"]

    lead_after = await client.get(f"{API}/leads/{lead_id}", headers=ws.headers)
    assert lead_after.status_code == 200
    assert lead_after.json()["status"] == "converted"
    assert lead_after.json()["deal_id"] == deal_id
    assert lead_after.json()["converted_at"] is not None

    # Trying to convert again is rejected.
    again = await client.post(
        f"{API}/leads/{lead_id}/convert",
        headers=ws.headers,
        json={"name": "Second Deal"},
    )
    assert again.status_code == 409


async def test_workspace_isolation(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="iso-a")
    ws_b = await register_workspace(client, slug_prefix="iso-b")

    qualified_a = await _stage_id_by_name(client, ws_a.headers, "Qualified")
    deal_a = await client.post(
        f"{API}/deals",
        headers=ws_a.headers,
        json={"name": "A-only", "pipeline_stage_id": qualified_a},
    )
    assert deal_a.status_code == 201
    a_deal_id = deal_a.json()["id"]

    # B cannot see A's deal.
    b_list = await client.get(f"{API}/deals", headers=ws_b.headers)
    assert b_list.json()["total"] == 0

    b_get = await client.get(f"{API}/deals/{a_deal_id}", headers=ws_b.headers)
    assert b_get.status_code == 404

    # B trying to use A's stage fails before write.
    bad_stage_deal = await client.post(
        f"{API}/deals",
        headers=ws_b.headers,
        json={"name": "Cross-tenant attack", "pipeline_stage_id": qualified_a},
    )
    assert bad_stage_deal.status_code == 400
