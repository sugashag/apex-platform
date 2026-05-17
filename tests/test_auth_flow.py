"""End-to-end registration → login → me happy path.

Requires a running Postgres reachable via DATABASE_URL. In CI a fresh
database is created and migrated before this test runs.
"""

import uuid

import pytest
from httpx import AsyncClient


@pytest.fixture
def fresh_slug() -> str:
    return f"ws-{uuid.uuid4().hex[:8]}"


async def test_register_login_me(client: AsyncClient, fresh_slug: str) -> None:
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    password = "correct-horse-battery-staple"

    # Register
    register_resp = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Ada",
            "last_name": "Lovelace",
            "workspace_name": "Test Workspace",
            "workspace_slug": fresh_slug,
        },
    )
    assert register_resp.status_code == 201, register_resp.text
    register_token = register_resp.json()["access_token"]
    assert register_token

    # Login
    login_resp = await client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 200, login_resp.text
    login_token = login_resp.json()["access_token"]

    # Me
    me_resp = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {login_token}"},
    )
    assert me_resp.status_code == 200, me_resp.text
    body = me_resp.json()
    assert body["email"] == email
    assert body["role"] == "admin"


async def test_login_with_wrong_password_fails(
    client: AsyncClient,
    fresh_slug: str,
) -> None:
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "the-right-password",
            "workspace_name": "WS",
            "workspace_slug": fresh_slug,
        },
    )

    bad = await client.post(
        "/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert bad.status_code == 401


async def test_me_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
