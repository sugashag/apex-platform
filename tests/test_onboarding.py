"""Onboarding checklist auto-evaluation + manual step completion."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def test_initial_checklist_has_no_steps_completed(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    resp = await client.get(f"{API}/onboarding", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["completed_at"] is None
    # The pipeline default is 6 stages exactly — configure_pipeline stays False
    # until the workspace adds an extra stage.
    assert body["configure_pipeline"] is False
    assert body["create_first_deal"] is False
    assert body["import_contacts"] is False


async def test_auto_detects_create_first_deal_and_pipeline(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    # Create a deal so the checklist's create_first_deal flips to True.
    stages_resp = await client.get(
        f"{API}/pipeline-stages", headers=ws.headers
    )
    assert stages_resp.status_code == 200
    stages = stages_resp.json()
    stage_id = stages[0]["id"]

    deal_resp = await client.post(
        f"{API}/deals",
        headers=ws.headers,
        json={"name": "First", "pipeline_stage_id": stage_id, "value_cents": 1000},
    )
    assert deal_resp.status_code == 201, deal_resp.text

    # Add a custom 7th pipeline stage so configure_pipeline flips.
    custom_stage = await client.post(
        f"{API}/pipeline-stages",
        headers=ws.headers,
        json={"name": "Custom", "position": 7, "probability_default": 25},
    )
    assert custom_stage.status_code == 201, custom_stage.text

    checklist = (
        await client.get(f"{API}/onboarding", headers=ws.headers)
    ).json()
    assert checklist["create_first_deal"] is True
    assert checklist["configure_pipeline"] is True


async def test_auto_detects_import_contacts(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    for i in range(5):
        suffix = uuid.uuid4().hex[:6]
        resp = await client.post(
            f"{API}/contacts",
            headers=ws.headers,
            json={"email": f"u{i}-{suffix}@example.com"},
        )
        assert resp.status_code == 201
    checklist = (
        await client.get(f"{API}/onboarding", headers=ws.headers)
    ).json()
    assert checklist["import_contacts"] is True


async def test_mark_step_complete(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    resp = await client.post(
        f"{API}/onboarding/install_tracking_snippet/complete",
        headers=ws.headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["install_tracking_snippet"] is True


async def test_mark_unknown_step_returns_400(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    resp = await client.post(
        f"{API}/onboarding/totally_bogus/complete", headers=ws.headers
    )
    assert resp.status_code == 400
