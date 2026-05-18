"""SLA-breach detection — ensure check_sla_breaches fires the workflow engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.thread import Thread
from app.models.workflow_run import WorkflowRun
from app.worker.jobs import check_sla_breaches
from tests.helpers import register_workspace

API = "/api/v1"


async def _new_contact(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={"email": f"c-{uuid.uuid4().hex[:6]}@example.com"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_thread(
    client: AsyncClient, headers: dict[str, str], contact_id: str
) -> str:
    resp = await client.post(
        f"{API}/inbox/threads",
        headers=headers,
        json={
            "subject": "SLA test",
            "to_emails": [f"to-{uuid.uuid4().hex[:6]}@example.com"],
            "body_text": "hello",
            "contact_id": contact_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_breach_fires_workflow_engine(client: AsyncClient) -> None:
    ws = await register_workspace(client)

    # Register a workflow that listens for SLA breaches.
    await client.post(
        f"{API}/workflows",
        headers=ws.headers,
        json={
            "name": "SLA escalator",
            "trigger_type": "sla_breached",
            "steps": [
                {
                    "position": 0,
                    "action_type": "create_activity",
                    "action_config": {
                        "type": "note",
                        "subject": "SLA breach!",
                    },
                }
            ],
        },
    )

    contact_id = await _new_contact(client, ws.headers)
    thread_id = await _create_thread(client, ws.headers, contact_id)

    # Push the SLA deadline into the past and ensure first_responded_at is
    # None so the first-response branch fires.
    past = datetime.now(UTC) - timedelta(hours=1)
    async with SessionLocal() as db:
        thread = await db.get(Thread, uuid.UUID(thread_id))
        assert thread is not None
        thread.sla_first_response_due_at = past
        thread.sla_resolution_due_at = past
        thread.first_responded_at = None
        await db.commit()

    fired = await check_sla_breaches({})
    assert fired >= 1

    async with SessionLocal() as db:
        runs = (
            await db.execute(
                select(WorkflowRun).where(WorkflowRun.trigger_type == "sla_breached")
            )
        ).scalars().all()
    assert runs, "expected at least one sla_breached workflow run"
