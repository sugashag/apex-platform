"""Workflow CRUD, manual trigger, condition gating, and step execution."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.workflow_run import WorkflowRun, WorkflowRunStatus
from app.models.workflow_step_run import (
    WorkflowStepRun,
    WorkflowStepRunStatus,
)
from app.services import workflow_engine
from tests.helpers import register_workspace

API = "/api/v1"


async def _new_contact(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={
            "email": f"c-{uuid.uuid4().hex[:6]}@example.com",
            "first_name": "Pat",
            "source": "google_ads",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_lead(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    contact_id = await _new_contact(client, headers)
    resp = await client.post(
        f"{API}/leads",
        headers=headers,
        json={"contact_id": contact_id, "source": "inbound"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], contact_id


async def test_create_and_list_workflow(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    payload = {
        "name": "Notify on lead",
        "description": "Drop a note when a lead is created.",
        "trigger_type": "lead_created",
        "conditions": [],
        "steps": [
            {
                "position": 0,
                "action_type": "create_activity",
                "action_config": {
                    "type": "note",
                    "subject": "Hello {{contact.first_name}}",
                    "body": "New lead from {{contact.source}}",
                },
            }
        ],
    }
    resp = await client.post(f"{API}/workflows", headers=ws.headers, json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Notify on lead"
    assert len(body["steps"]) == 1
    assert body["steps"][0]["action_type"] == "create_activity"

    listed = await client.get(f"{API}/workflows", headers=ws.headers)
    assert listed.status_code == 200
    assert any(w["id"] == body["id"] for w in listed.json()["items"])


async def test_workflow_fires_on_lead_created_and_executes_step(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    await client.post(
        f"{API}/workflows",
        headers=ws.headers,
        json={
            "name": "Note on lead",
            "trigger_type": "lead_created",
            "steps": [
                {
                    "position": 0,
                    "action_type": "create_activity",
                    "action_config": {
                        "type": "note",
                        "subject": "New lead {{contact.first_name}}",
                    },
                }
            ],
        },
    )

    _lead_id, _contact_id = await _new_lead(client, ws.headers)

    # A run was created. Since the first step has no delay and Redis is
    # offline in tests, the step run is pending until the cron poller fires.
    # Execute it directly through the engine to verify the action runs.
    async with SessionLocal() as db:
        runs_result = await db.execute(
            select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(1)
        )
        run = runs_result.scalar_one()
        assert run.trigger_type == "lead_created"

        step_run_result = await db.execute(
            select(WorkflowStepRun).where(WorkflowStepRun.workflow_run_id == run.id)
        )
        step_run = step_run_result.scalar_one()
        await workflow_engine.execute_step(db, step_run.id)

        refreshed = await db.get(WorkflowRun, run.id)
        assert refreshed is not None
        assert refreshed.status == WorkflowRunStatus.COMPLETED
        refreshed_sr = await db.get(WorkflowStepRun, step_run.id)
        assert refreshed_sr is not None
        assert refreshed_sr.status == WorkflowStepRunStatus.COMPLETED
        assert refreshed_sr.output is not None


async def test_workflow_conditions_gate_execution(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    # Workflow only fires when contact.source == 'facebook' (our seeds use
    # 'google_ads'), so the run count must stay at zero.
    create = await client.post(
        f"{API}/workflows",
        headers=ws.headers,
        json={
            "name": "Only Facebook",
            "trigger_type": "lead_created",
            "conditions": [
                {
                    "field": "contact.source",
                    "operator": "equals",
                    "value": "facebook",
                }
            ],
            "steps": [
                {
                    "position": 0,
                    "action_type": "create_activity",
                    "action_config": {"type": "note", "subject": "FB!"},
                }
            ],
        },
    )
    wf_id = create.json()["id"]

    await _new_lead(client, ws.headers)

    async with SessionLocal() as db:
        runs = await db.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf_id)
        )
        assert runs.scalars().first() is None


async def test_human_gate_pauses_run_and_approve_resumes(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    await client.post(
        f"{API}/workflows",
        headers=ws.headers,
        json={
            "name": "Gated",
            "trigger_type": "lead_created",
            "steps": [
                {
                    "position": 0,
                    "action_type": "human_gate",
                    "action_config": {},
                    "requires_approval": True,
                }
            ],
        },
    )
    await _new_lead(client, ws.headers)

    async with SessionLocal() as db:
        run = (
            await db.execute(
                select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(1)
            )
        ).scalar_one()
        assert run.status == WorkflowRunStatus.WAITING_APPROVAL
        step_run = (
            await db.execute(
                select(WorkflowStepRun).where(
                    WorkflowStepRun.workflow_run_id == run.id
                )
            )
        ).scalar_one()
        assert step_run.status == WorkflowStepRunStatus.WAITING_APPROVAL
        step_run_id = step_run.id

    approve = await client.post(
        f"{API}/workflow-step-runs/{step_run_id}/approve", headers=ws.headers
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"


async def test_manual_trigger_endpoint(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    create = await client.post(
        f"{API}/workflows",
        headers=ws.headers,
        json={
            "name": "Manual fire",
            "trigger_type": "manual",
            "steps": [
                {
                    "position": 0,
                    "action_type": "create_activity",
                    "action_config": {"type": "note", "subject": "manual"},
                }
            ],
        },
    )
    wf_id = create.json()["id"]
    fire = await client.post(
        f"{API}/workflows/{wf_id}/trigger",
        headers=ws.headers,
        json={
            "entity_type": "contact",
            "entity_id": contact_id,
            "context": {"contact_id": contact_id},
        },
    )
    assert fire.status_code == 201, fire.text
    assert len(fire.json()) == 1


async def test_workflow_run_audit_trail(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    create = await client.post(
        f"{API}/workflows",
        headers=ws.headers,
        json={
            "name": "Auditable",
            "trigger_type": "lead_created",
            "steps": [
                {
                    "position": 0,
                    "action_type": "create_activity",
                    "action_config": {"type": "note", "subject": "ok"},
                }
            ],
        },
    )
    wf_id = create.json()["id"]
    await _new_lead(client, ws.headers)

    runs = await client.get(
        f"{API}/workflow-runs?workflow_id={wf_id}", headers=ws.headers
    )
    assert runs.status_code == 200
    items = runs.json()["items"]
    assert items
    run_id = items[0]["id"]

    detail = await client.get(f"{API}/workflow-runs/{run_id}", headers=ws.headers)
    assert detail.status_code == 200
    assert "step_runs" in detail.json()
    assert len(detail.json()["step_runs"]) == 1


async def test_update_workflow_replaces_steps(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    create = await client.post(
        f"{API}/workflows",
        headers=ws.headers,
        json={
            "name": "Replaceable",
            "trigger_type": "lead_created",
            "steps": [
                {
                    "position": 0,
                    "action_type": "create_activity",
                    "action_config": {"type": "note", "subject": "v1"},
                }
            ],
        },
    )
    wf_id = create.json()["id"]
    updated = await client.patch(
        f"{API}/workflows/{wf_id}",
        headers=ws.headers,
        json={
            "steps": [
                {
                    "position": 0,
                    "action_type": "add_tag",
                    "action_config": {"tag": "vip"},
                }
            ]
        },
    )
    assert updated.status_code == 200, updated.text
    steps = updated.json()["steps"]
    assert len(steps) == 1
    assert steps[0]["action_type"] == "add_tag"


async def test_deactivate_workflow(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    create = await client.post(
        f"{API}/workflows",
        headers=ws.headers,
        json={
            "name": "Disable me",
            "trigger_type": "lead_created",
            "steps": [],
        },
    )
    wf_id = create.json()["id"]
    delete = await client.delete(f"{API}/workflows/{wf_id}", headers=ws.headers)
    assert delete.status_code == 204
    get = await client.get(f"{API}/workflows/{wf_id}", headers=ws.headers)
    assert get.status_code == 200
    assert get.json()["is_active"] is False
