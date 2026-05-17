"""Company CRUD + workspace-isolation tests."""

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def test_create_and_get_company(client: AsyncClient) -> None:
    ws = await register_workspace(client)

    resp = await client.post(
        f"{API}/companies",
        headers=ws.headers,
        json={"name": "Acme Inc", "domain": "acme.test", "industry": "Manufacturing"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    company_id = body["id"]
    assert body["name"] == "Acme Inc"
    assert body["domain"] == "acme.test"
    assert body["is_active"] is True

    detail = await client.get(f"{API}/companies/{company_id}", headers=ws.headers)
    assert detail.status_code == 200
    assert detail.json()["contact_count"] == 0


async def test_list_companies_pagination_and_search(client: AsyncClient) -> None:
    ws = await register_workspace(client)

    for i in range(3):
        resp = await client.post(
            f"{API}/companies",
            headers=ws.headers,
            json={"name": f"Acme {i}", "domain": f"acme{i}.test"},
        )
        assert resp.status_code == 201

    listed = await client.get(
        f"{API}/companies?page=1&page_size=2", headers=ws.headers,
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 3
    assert body["total_pages"] == 2
    assert len(body["items"]) == 2

    searched = await client.get(
        f"{API}/companies?search=acme1", headers=ws.headers,
    )
    assert searched.status_code == 200
    assert len(searched.json()["items"]) == 1


async def test_duplicate_domain_is_rejected(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    payload = {"name": "Acme", "domain": "dup.test"}

    first = await client.post(f"{API}/companies", headers=ws.headers, json=payload)
    assert first.status_code == 201

    second = await client.post(f"{API}/companies", headers=ws.headers, json=payload)
    assert second.status_code == 409


async def test_update_and_soft_delete(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    created = await client.post(
        f"{API}/companies",
        headers=ws.headers,
        json={"name": "Old", "domain": "x.test"},
    )
    company_id = created.json()["id"]

    patched = await client.patch(
        f"{API}/companies/{company_id}",
        headers=ws.headers,
        json={"name": "New", "industry": "Tech"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "New"
    assert patched.json()["industry"] == "Tech"

    deleted = await client.delete(
        f"{API}/companies/{company_id}", headers=ws.headers,
    )
    assert deleted.status_code == 204

    listed = await client.get(f"{API}/companies", headers=ws.headers)
    assert all(item["id"] != company_id for item in listed.json()["items"])


async def test_workspace_isolation(client: AsyncClient) -> None:
    """Workspace A's companies must be invisible to workspace B."""
    ws_a = await register_workspace(client, slug_prefix="iso-a")
    ws_b = await register_workspace(client, slug_prefix="iso-b")

    created = await client.post(
        f"{API}/companies",
        headers=ws_a.headers,
        json={"name": "Tenant A Only", "domain": "tenant-a.test"},
    )
    assert created.status_code == 201
    a_company_id = created.json()["id"]

    # B can't see A's list
    b_list = await client.get(f"{API}/companies", headers=ws_b.headers)
    assert b_list.status_code == 200
    assert b_list.json()["total"] == 0

    # B can't GET A's company
    b_get = await client.get(
        f"{API}/companies/{a_company_id}", headers=ws_b.headers,
    )
    assert b_get.status_code == 404

    # B can't PATCH A's company
    b_patch = await client.patch(
        f"{API}/companies/{a_company_id}",
        headers=ws_b.headers,
        json={"name": "Hacked"},
    )
    assert b_patch.status_code == 404

    # B can't DELETE A's company
    b_delete = await client.delete(
        f"{API}/companies/{a_company_id}", headers=ws_b.headers,
    )
    assert b_delete.status_code == 404

    # Same domain is allowed in different workspaces.
    b_create = await client.post(
        f"{API}/companies",
        headers=ws_b.headers,
        json={"name": "Tenant B Same Domain", "domain": "tenant-a.test"},
    )
    assert b_create.status_code == 201


async def test_auth_required(client: AsyncClient) -> None:
    resp = await client.get(f"{API}/companies")
    assert resp.status_code == 401
