"""Contact CRUD, search, dedup, workspace isolation tests."""

import uuid

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def test_create_and_list_contact(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    suffix = uuid.uuid4().hex[:6]
    email = f"ada-{suffix}@example.com"

    resp = await client.post(
        f"{API}/contacts",
        headers=ws.headers,
        json={
            "email": email,
            "first_name": "Ada",
            "last_name": "Lovelace",
            "source": "referral",
            "lead_score": 42,
        },
    )
    assert resp.status_code == 201, resp.text
    contact_id = resp.json()["id"]

    detail = await client.get(f"{API}/contacts/{contact_id}", headers=ws.headers)
    assert detail.status_code == 200
    assert detail.json()["email"] == email
    assert detail.json()["recent_activities"] == []


async def test_duplicate_email_in_same_workspace_is_rejected(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    email = f"dup-{uuid.uuid4().hex[:6]}@example.com"

    first = await client.post(
        f"{API}/contacts", headers=ws.headers, json={"email": email},
    )
    assert first.status_code == 201

    second = await client.post(
        f"{API}/contacts", headers=ws.headers, json={"email": email},
    )
    assert second.status_code == 409


async def test_search_and_filter(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    suffix = uuid.uuid4().hex[:6]
    await client.post(
        f"{API}/contacts",
        headers=ws.headers,
        json={
            "email": f"alice-{suffix}@example.com", "first_name": "Alice",
            "source": "google_ads", "lead_score": 10,
        },
    )
    await client.post(
        f"{API}/contacts",
        headers=ws.headers,
        json={
            "email": f"bob-{suffix}@example.com", "first_name": "Bob",
            "source": "referral", "lead_score": 90,
        },
    )

    by_name = await client.get(
        f"{API}/contacts?search=alice-{suffix}", headers=ws.headers,
    )
    assert by_name.status_code == 200
    items = by_name.json()["items"]
    assert len(items) == 1
    assert items[0]["first_name"] == "Alice"

    by_score = await client.get(
        f"{API}/contacts?lead_score_min=50", headers=ws.headers,
    )
    assert by_score.status_code == 200
    scored_items = by_score.json()["items"]
    assert all(c["lead_score"] >= 50 for c in scored_items)
    assert any(c["first_name"] == "Bob" for c in scored_items)


async def test_workspace_isolation(client: AsyncClient) -> None:
    """Contacts in one workspace must not be visible from another."""
    ws_a = await register_workspace(client, slug_prefix="iso-a")
    ws_b = await register_workspace(client, slug_prefix="iso-b")

    email = f"shared-{uuid.uuid4().hex[:6]}@example.com"
    a_create = await client.post(
        f"{API}/contacts", headers=ws_a.headers, json={"email": email},
    )
    assert a_create.status_code == 201
    a_contact_id = a_create.json()["id"]

    # Same email reused in another workspace is allowed.
    b_create = await client.post(
        f"{API}/contacts", headers=ws_b.headers, json={"email": email},
    )
    assert b_create.status_code == 201

    # B's list does not contain A's contact.
    b_list = await client.get(f"{API}/contacts", headers=ws_b.headers)
    assert b_list.status_code == 200
    assert all(item["id"] != a_contact_id for item in b_list.json()["items"])

    # B cannot read A's contact directly.
    b_get = await client.get(
        f"{API}/contacts/{a_contact_id}", headers=ws_b.headers,
    )
    assert b_get.status_code == 404


async def test_update_and_soft_delete(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    email = f"upd-{uuid.uuid4().hex[:6]}@example.com"
    created = await client.post(
        f"{API}/contacts", headers=ws.headers, json={"email": email},
    )
    contact_id = created.json()["id"]

    patched = await client.patch(
        f"{API}/contacts/{contact_id}",
        headers=ws.headers,
        json={"first_name": "Updated", "lead_score": 75},
    )
    assert patched.status_code == 200
    assert patched.json()["first_name"] == "Updated"
    assert patched.json()["lead_score"] == 75

    deleted = await client.delete(
        f"{API}/contacts/{contact_id}", headers=ws.headers,
    )
    assert deleted.status_code == 204

    listed = await client.get(f"{API}/contacts", headers=ws.headers)
    assert all(item["id"] != contact_id for item in listed.json()["items"])
