"""Shared-inbox thread lifecycle + workspace isolation tests."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def _new_contact(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={"email": f"c-{uuid.uuid4().hex[:6]}@example.com"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_thread(
    client: AsyncClient, headers: dict[str, str], *, contact_id: str | None = None
) -> str:
    payload = {
        "subject": f"Hello {uuid.uuid4().hex[:6]}",
        "to_emails": [f"target-{uuid.uuid4().hex[:6]}@example.com"],
        "body_text": "Hi there",
    }
    if contact_id:
        payload["contact_id"] = contact_id
    resp = await client.post(f"{API}/inbox/threads", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_create_and_list_threads(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)

    thread_id = await _create_thread(client, ws.headers, contact_id=contact_id)

    listed = await client.get(f"{API}/inbox", headers=ws.headers)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert any(t["id"] == thread_id for t in items)
    match = next(t for t in items if t["id"] == thread_id)
    assert match["contact_id"] == contact_id
    assert match["message_count"] >= 1


async def test_assign_and_resolve_thread(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    thread_id = await _create_thread(client, ws.headers)

    # Find the workspace's only user id from the auth /me endpoint? Simpler:
    # the user we just registered owns the thread already; introspect via list.
    me = await client.get("/auth/me", headers=ws.headers)
    assert me.status_code == 200
    user_id = me.json()["id"]

    assign = await client.post(
        f"{API}/inbox/{thread_id}/assign",
        headers=ws.headers,
        json={"assignee_id": user_id},
    )
    assert assign.status_code == 200
    assert assign.json()["assignee_id"] == user_id

    resolve = await client.post(
        f"{API}/inbox/{thread_id}/resolve", headers=ws.headers
    )
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "resolved"
    assert resolve.json()["resolved_at"] is not None

    reopen = await client.post(
        f"{API}/inbox/{thread_id}/reopen", headers=ws.headers
    )
    assert reopen.status_code == 200
    assert reopen.json()["status"] == "open"
    assert reopen.json()["resolved_at"] is None


async def test_snooze_thread(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    thread_id = await _create_thread(client, ws.headers)

    later = datetime.now(UTC) + timedelta(hours=2)
    resp = await client.post(
        f"{API}/inbox/{thread_id}/snooze",
        headers=ws.headers,
        json={"snoozed_until": later.isoformat()},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "snoozed"
    assert resp.json()["snoozed_until"] is not None


async def test_reply_creates_outbound_message(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    thread_id = await _create_thread(client, ws.headers, contact_id=contact_id)

    reply = await client.post(
        f"{API}/inbox/{thread_id}/reply",
        headers=ws.headers,
        json={"body_text": "Thanks for reaching out!"},
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["direction"] == "outbound"

    detail = await client.get(f"{API}/inbox/{thread_id}", headers=ws.headers)
    assert detail.status_code == 200
    msgs = detail.json()["messages"]
    assert len(msgs) >= 2  # initial compose + reply
    outbound = [m for m in msgs if m["direction"] == "outbound"]
    assert any("Thanks for reaching out" in (m["body_text"] or "") for m in outbound)


async def test_reply_requires_body(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    thread_id = await _create_thread(client, ws.headers, contact_id=contact_id)
    resp = await client.post(
        f"{API}/inbox/{thread_id}/reply", headers=ws.headers, json={}
    )
    assert resp.status_code == 422


async def test_inbox_workspace_isolation(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="inbox-a")
    ws_b = await register_workspace(client, slug_prefix="inbox-b")

    thread_id = await _create_thread(client, ws_a.headers)

    # B cannot see A's thread.
    b_list = await client.get(f"{API}/inbox", headers=ws_b.headers)
    assert b_list.status_code == 200
    assert all(t["id"] != thread_id for t in b_list.json()["items"])

    b_get = await client.get(f"{API}/inbox/{thread_id}", headers=ws_b.headers)
    assert b_get.status_code == 404
