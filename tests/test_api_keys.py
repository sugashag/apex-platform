"""API key creation, listing, revocation, and X-API-Key authentication."""

from __future__ import annotations

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def test_create_key_returns_full_key_once(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    resp = await client.post(
        f"{API}/api-keys",
        headers=ws.headers,
        json={"name": "Zapier integration", "scopes": ["contacts:read"]},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["full_key"].startswith("apex_live_")
    assert body["key_prefix"] == "apex_live_"
    assert body["scopes"] == ["contacts:read"]


async def test_list_keys_does_not_expose_full_key(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    created = await client.post(
        f"{API}/api-keys", headers=ws.headers, json={"name": "k1"}
    )
    assert created.status_code == 201
    listed = await client.get(f"{API}/api-keys", headers=ws.headers)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    # Plain listing schema has no `full_key` field at all.
    assert "full_key" not in items[0]
    assert items[0]["key_prefix"] == "apex_live_"


async def test_api_key_authenticates_requests(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    created = await client.post(
        f"{API}/api-keys", headers=ws.headers, json={"name": "integration"}
    )
    full_key = created.json()["full_key"]

    # Use API key, no Bearer token.
    resp = await client.get(f"{API}/contacts", headers={"X-API-Key": full_key})
    assert resp.status_code == 200


async def test_invalid_api_key_returns_401(client: AsyncClient) -> None:
    resp = await client.get(
        f"{API}/contacts", headers={"X-API-Key": "apex_live_definitely_invalid"}
    )
    assert resp.status_code == 401


async def test_revoked_key_no_longer_works(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    created = await client.post(
        f"{API}/api-keys", headers=ws.headers, json={"name": "k"}
    )
    full_key = created.json()["full_key"]
    key_id = created.json()["id"]

    deleted = await client.delete(f"{API}/api-keys/{key_id}", headers=ws.headers)
    assert deleted.status_code == 204

    after = await client.get(f"{API}/contacts", headers={"X-API-Key": full_key})
    assert after.status_code == 401


async def test_api_key_workspace_isolation(client: AsyncClient) -> None:
    """A key from workspace A must not authenticate calls scoped to workspace B."""
    ws_a = await register_workspace(client, slug_prefix="key-a")
    ws_b = await register_workspace(client, slug_prefix="key-b")

    # Create a contact in B (using B's bearer token).
    b_contact = await client.post(
        f"{API}/contacts",
        headers=ws_b.headers,
        json={"email": "iso@example.com"},
    )
    assert b_contact.status_code == 201
    b_contact_id = b_contact.json()["id"]

    # Create an API key in A.
    a_key = (
        await client.post(
            f"{API}/api-keys", headers=ws_a.headers, json={"name": "a"}
        )
    ).json()["full_key"]

    # Calls scoped by workspace (current_user.workspace_id == A) won't see B's contact.
    a_view = await client.get(
        f"{API}/contacts/{b_contact_id}", headers={"X-API-Key": a_key}
    )
    assert a_view.status_code == 404
