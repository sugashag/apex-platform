"""Plan-limit enforcement — user cap, contact cap, NetSuite gate."""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.plan import Plan
from app.models.workspace_subscription import WorkspaceSubscription
from tests.helpers import register_workspace

API = "/api/v1"


async def _attach_plan_with_limits(
    workspace_id: UUID,
    *,
    max_users: int | None = None,
    max_contacts: int | None = None,
    includes_netsuite: bool = False,
    includes_ai_agents: bool = True,
    name: str = "Test Plan",
) -> Plan:
    """Create a fresh plan and re-point the workspace's subscription at it."""
    slug = f"test-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as session:
        plan = Plan(
            name=name,
            slug=slug,
            price_cents_monthly=1,
            price_cents_annual=10,
            max_users=max_users,
            max_contacts=max_contacts,
            includes_netsuite=includes_netsuite,
            includes_ai_agents=includes_ai_agents,
        )
        session.add(plan)
        await session.flush()

        sub_result = await session.execute(
            select(WorkspaceSubscription).where(
                WorkspaceSubscription.workspace_id == workspace_id
            )
        )
        subscription = sub_result.scalar_one()
        subscription.plan_id = plan.id
        await session.commit()
        await session.refresh(plan)
        return plan


async def test_contact_limit_blocks_creation(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    me = (await client.get("/auth/me", headers=ws.headers)).json()
    await _attach_plan_with_limits(UUID(me["workspace_id"]), max_contacts=2)

    # First two contacts succeed.
    for i in range(2):
        resp = await client.post(
            f"{API}/contacts",
            headers=ws.headers,
            json={"email": f"limit-{i}-{uuid.uuid4().hex[:6]}@example.com"},
        )
        assert resp.status_code == 201, resp.text

    # Third hits the limit.
    blocked = await client.post(
        f"{API}/contacts",
        headers=ws.headers,
        json={"email": f"over-{uuid.uuid4().hex[:6]}@example.com"},
    )
    assert blocked.status_code == 402
    assert "Plan limit" in blocked.json()["detail"]


async def test_user_invite_limit_blocks_new_invites(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    me = (await client.get("/auth/me", headers=ws.headers)).json()
    # max_users=1 — there's already one active user (the admin).
    await _attach_plan_with_limits(UUID(me["workspace_id"]), max_users=1)

    resp = await client.post(
        f"{API}/users/invite",
        headers=ws.headers,
        json={"email": f"u-{uuid.uuid4().hex[:6]}@example.com", "role": "rep"},
    )
    assert resp.status_code == 402


async def test_netsuite_blocked_on_starter_plan(client: AsyncClient) -> None:
    """Starter plan ships with includes_netsuite=False — config must be blocked."""
    ws = await register_workspace(client)
    resp = await client.post(
        "/api/v1/netsuite/config",
        headers=ws.headers,
        json={
            "account_id": "TSTDRV0000",
            "consumer_key": "ck",
            "consumer_secret": "cs",
            "token_id": "ti",
            "token_secret": "ts",
        },
    )
    assert resp.status_code == 402
    assert "NetSuite" in resp.json()["detail"]


async def test_netsuite_allowed_on_growth_plan(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    plans = (await client.get(f"{API}/billing/plans")).json()
    growth = next(p for p in plans if p["slug"] == "growth")
    upgrade = await client.post(
        f"{API}/billing/subscribe",
        headers=ws.headers,
        json={
            "plan_id": growth["id"],
            "billing_email": "billing@example.com",
            "billing_name": "Test",
        },
    )
    assert upgrade.status_code == 201

    resp = await client.post(
        "/api/v1/netsuite/config",
        headers=ws.headers,
        json={
            "account_id": "TSTDRV0000",
            "consumer_key": "ck",
            "consumer_secret": "cs",
            "token_id": "ti",
            "token_secret": "ts",
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("path", ["agents/leads"])
async def test_ai_agents_blocked_when_plan_disallows(
    client: AsyncClient, path: str
) -> None:
    """An agent invocation must return 402 when includes_ai_agents=False."""
    ws = await register_workspace(client)
    me = (await client.get("/auth/me", headers=ws.headers)).json()
    await _attach_plan_with_limits(
        UUID(me["workspace_id"]),
        includes_ai_agents=False,
    )

    contact_resp = await client.post(
        f"{API}/contacts",
        headers=ws.headers,
        json={"email": f"l-{uuid.uuid4().hex[:6]}@example.com"},
    )
    assert contact_resp.status_code == 201, contact_resp.text
    contact_id = contact_resp.json()["id"]

    lead_resp = await client.post(
        f"{API}/leads",
        headers=ws.headers,
        json={"contact_id": contact_id},
    )
    assert lead_resp.status_code == 201, lead_resp.text
    lead_id = lead_resp.json()["id"]

    resp = await client.post(
        f"{API}/agents/leads/{lead_id}/score", headers=ws.headers
    )
    assert resp.status_code == 402
