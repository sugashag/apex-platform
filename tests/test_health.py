"""Smoke test for the health endpoint."""

from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "version" in body
    assert "environment" in body
    assert "database" in body


async def test_root_returns_metadata(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "apex"
    assert "version" in body
