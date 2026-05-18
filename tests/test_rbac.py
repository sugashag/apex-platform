"""Role-based access control coverage on Phase 8 protected endpoints."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def _spawn_user_with_role(
    client: AsyncClient, ws_headers: dict[str, str], role: str
) -> dict[str, str]:
    """Invite a user, log them in, return Authorization headers."""
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    invite = await client.post(
        f"{API}/users/invite",
        headers=ws_headers,
        json={"email": email, "role": role},
    )
    assert invite.status_code == 201, invite.text
    temp_pw = invite.json()["temporary_password"]
    login = await client.post(
        "/auth/login", json={"email": email, "password": temp_pw}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_rep_cannot_delete_contacts(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact = await client.post(
        f"{API}/contacts",
        headers=ws.headers,
        json={"email": f"c-{uuid.uuid4().hex[:6]}@example.com"},
    )
    contact_id = contact.json()["id"]

    rep_headers = await _spawn_user_with_role(client, ws.headers, "rep")
    blocked = await client.delete(
        f"{API}/contacts/{contact_id}", headers=rep_headers
    )
    assert blocked.status_code == 403


async def test_manager_can_delete_contacts(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact = await client.post(
        f"{API}/contacts",
        headers=ws.headers,
        json={"email": f"c-{uuid.uuid4().hex[:6]}@example.com"},
    )
    contact_id = contact.json()["id"]

    mgr_headers = await _spawn_user_with_role(client, ws.headers, "manager")
    ok = await client.delete(
        f"{API}/contacts/{contact_id}", headers=mgr_headers
    )
    assert ok.status_code == 204


async def test_rep_cannot_delete_deals(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    stages = (
        await client.get(f"{API}/pipeline-stages", headers=ws.headers)
    ).json()
    deal = await client.post(
        f"{API}/deals",
        headers=ws.headers,
        json={
            "name": "Test",
            "pipeline_stage_id": stages[0]["id"],
            "value_cents": 100,
        },
    )
    deal_id = deal.json()["id"]

    rep_headers = await _spawn_user_with_role(client, ws.headers, "rep")
    blocked = await client.delete(f"{API}/deals/{deal_id}", headers=rep_headers)
    assert blocked.status_code == 403


async def test_rep_cannot_create_workflow(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    rep_headers = await _spawn_user_with_role(client, ws.headers, "rep")
    resp = await client.post(
        f"{API}/workflows",
        headers=rep_headers,
        json={
            "name": "test",
            "trigger_type": "lead_created",
            "is_active": True,
            "trigger_config": {},
            "conditions": [],
            "steps": [],
        },
    )
    assert resp.status_code == 403


async def test_manager_cannot_create_api_key(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    mgr_headers = await _spawn_user_with_role(client, ws.headers, "manager")
    resp = await client.post(
        f"{API}/api-keys", headers=mgr_headers, json={"name": "x"}
    )
    assert resp.status_code == 403


async def test_manager_cannot_invite_users(client: AsyncClient) -> None:
    """Invite is admin-only — managers must be blocked."""
    ws = await register_workspace(client)
    mgr_headers = await _spawn_user_with_role(client, ws.headers, "manager")
    resp = await client.post(
        f"{API}/users/invite",
        headers=mgr_headers,
        json={"email": f"new-{uuid.uuid4().hex[:6]}@example.com", "role": "rep"},
    )
    assert resp.status_code == 403


async def test_rep_cannot_configure_netsuite(client: AsyncClient) -> None:
    """NetSuite config is admin-only (and gated by plan, but RBAC fires first)."""
    ws = await register_workspace(client)
    rep_headers = await _spawn_user_with_role(client, ws.headers, "rep")
    resp = await client.post(
        f"{API}/netsuite/config",
        headers=rep_headers,
        json={
            "account_id": "X",
            "consumer_key": "ck",
            "consumer_secret": "cs",
            "token_id": "ti",
            "token_secret": "ts",
        },
    )
    assert resp.status_code == 403


async def test_rep_cannot_view_revenue_by_rep(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    rep_headers = await _spawn_user_with_role(client, ws.headers, "rep")
    resp = await client.get(
        f"{API}/reports/revenue/by-rep", headers=rep_headers
    )
    assert resp.status_code == 403


async def test_admin_passes_all_checks(client: AsyncClient) -> None:
    """Sanity: admin role passes the RBAC dependencies."""
    ws = await register_workspace(client)
    resp = await client.post(
        f"{API}/api-keys", headers=ws.headers, json={"name": "ok"}
    )
    assert resp.status_code == 201
