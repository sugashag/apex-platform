"""SMS send + list + workspace isolation tests."""

import uuid

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def _new_contact(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={"email": f"c-{uuid.uuid4().hex[:6]}@example.com", "phone": "+15551112222"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_send_sms(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)

    resp = await client.post(
        f"{API}/sms",
        headers=ws.headers,
        json={
            "to_number": "+15551112222",
            "from_number": "+15558889999",
            "body": "Hi there!",
            "contact_id": contact_id,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["direction"] == "outbound"
    assert body["status"] == "sent"
    assert body["twilio_message_sid"] is not None
    assert body["body"] == "Hi there!"
    assert body["contact_id"] == contact_id


async def test_send_sms_creates_activity(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    await client.post(
        f"{API}/sms",
        headers=ws.headers,
        json={
            "to_number": "+15551112222",
            "from_number": "+15558889999",
            "body": "Test",
            "contact_id": contact_id,
        },
    )
    timeline = await client.get(
        f"{API}/contacts/{contact_id}/timeline", headers=ws.headers
    )
    assert timeline.status_code == 200
    assert any(a["type"] == "sms" for a in timeline.json()["items"])


async def test_list_sms_filters(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    a = await _new_contact(client, ws.headers)
    b = await _new_contact(client, ws.headers)
    await client.post(
        f"{API}/sms",
        headers=ws.headers,
        json={
            "to_number": "+15551112222",
            "from_number": "+15558889999",
            "body": "A",
            "contact_id": a,
        },
    )
    await client.post(
        f"{API}/sms",
        headers=ws.headers,
        json={
            "to_number": "+15553334444",
            "from_number": "+15558889999",
            "body": "B",
            "contact_id": b,
        },
    )

    listed = await client.get(f"{API}/sms?contact_id={a}", headers=ws.headers)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["contact_id"] == a


async def test_sms_workspace_isolation(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="sms-a")
    ws_b = await register_workspace(client, slug_prefix="sms-b")

    sent = await client.post(
        f"{API}/sms",
        headers=ws_a.headers,
        json={
            "to_number": "+15551112222",
            "from_number": "+15558889999",
            "body": "secret",
        },
    )
    sms_id = sent.json()["id"]

    b_list = await client.get(f"{API}/sms", headers=ws_b.headers)
    assert b_list.status_code == 200
    assert all(m["id"] != sms_id for m in b_list.json()["items"])
