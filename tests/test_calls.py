"""Call lifecycle + workspace isolation tests.

External Twilio calls are mocked at the service layer — `twilio_service`
already degrades to mock SIDs when `TWILIO_ACCOUNT_SID` is unset (the
default in CI), so no extra monkeypatching is required.
"""

import uuid

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def _new_contact(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={"email": f"c-{uuid.uuid4().hex[:6]}@example.com", "phone": "+15551234567"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_initiate_call(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)

    resp = await client.post(
        f"{API}/calls",
        headers=ws.headers,
        json={
            "to_number": "+15551234567",
            "from_number": "+15559998888",
            "contact_id": contact_id,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["direction"] == "outbound"
    assert body["status"] == "initiated"
    assert body["twilio_call_sid"] is not None
    assert body["from_number"] == "+15559998888"
    assert body["to_number"] == "+15551234567"
    assert body["contact_id"] == contact_id


async def test_complete_call_creates_activity(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)

    created = await client.post(
        f"{API}/calls",
        headers=ws.headers,
        json={
            "to_number": "+15551234567",
            "from_number": "+15559998888",
            "contact_id": contact_id,
        },
    )
    call_id = created.json()["id"]

    patched = await client.patch(
        f"{API}/calls/{call_id}",
        headers=ws.headers,
        json={"duration_seconds": 125, "transcript": "Hi, this is a test call."},
    )
    assert patched.status_code == 200
    assert patched.json()["duration_seconds"] == 125
    assert patched.json()["duration_formatted"] == "02:05"

    completed = await client.post(
        f"{API}/calls/{call_id}/complete", headers=ws.headers
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["ended_at"] is not None

    timeline = await client.get(
        f"{API}/contacts/{contact_id}/timeline", headers=ws.headers
    )
    assert timeline.status_code == 200
    types = [a["type"] for a in timeline.json()["items"]]
    assert "call" in types


async def test_list_calls_filters_by_contact(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    a = await _new_contact(client, ws.headers)
    b = await _new_contact(client, ws.headers)

    await client.post(
        f"{API}/calls",
        headers=ws.headers,
        json={"to_number": "+15551110000", "from_number": "+15559998888", "contact_id": a},
    )
    await client.post(
        f"{API}/calls",
        headers=ws.headers,
        json={"to_number": "+15552220000", "from_number": "+15559998888", "contact_id": b},
    )

    listed_a = await client.get(
        f"{API}/calls?contact_id={a}", headers=ws.headers
    )
    assert listed_a.status_code == 200
    items = listed_a.json()["items"]
    assert len(items) == 1
    assert items[0]["contact_id"] == a


async def test_call_token_returns_string(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    resp = await client.get(f"{API}/calls/token", headers=ws.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["token"], str) and body["token"]
    assert body["identity"].startswith("user-")
    assert body["expires_in_seconds"] > 0


async def test_calls_workspace_isolation(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="call-a")
    ws_b = await register_workspace(client, slug_prefix="call-b")

    created = await client.post(
        f"{API}/calls",
        headers=ws_a.headers,
        json={"to_number": "+15551234567", "from_number": "+15559998888"},
    )
    call_id = created.json()["id"]

    b_get = await client.get(f"{API}/calls/{call_id}", headers=ws_b.headers)
    assert b_get.status_code == 404

    b_list = await client.get(f"{API}/calls", headers=ws_b.headers)
    assert b_list.status_code == 200
    assert all(c["id"] != call_id for c in b_list.json()["items"])
