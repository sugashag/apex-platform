"""User management — invite, list, role updates, deactivation, RBAC."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


def _new_email() -> str:
    return f"invited-{uuid.uuid4().hex[:6]}@example.com"


async def test_admin_can_invite_user(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    email = _new_email()
    resp = await client.post(
        f"{API}/users/invite",
        headers=ws.headers,
        json={
            "email": email,
            "first_name": "Inv",
            "last_name": "Itee",
            "role": "rep",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["email"] == email
    assert body["user"]["role"] == "rep"
    assert body["temporary_password"]


async def test_invited_user_can_login(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    email = _new_email()
    invite = await client.post(
        f"{API}/users/invite",
        headers=ws.headers,
        json={"email": email, "role": "rep"},
    )
    temp_pw = invite.json()["temporary_password"]

    login = await client.post(
        "/auth/login", json={"email": email, "password": temp_pw}
    )
    assert login.status_code == 200


async def test_rep_cannot_invite(client: AsyncClient) -> None:
    """RBAC: rep-role users cannot invite teammates."""
    ws = await register_workspace(client)
    rep_email = _new_email()
    invite_rep = await client.post(
        f"{API}/users/invite",
        headers=ws.headers,
        json={"email": rep_email, "role": "rep"},
    )
    rep_pw = invite_rep.json()["temporary_password"]
    rep_token = (
        await client.post(
            "/auth/login", json={"email": rep_email, "password": rep_pw}
        )
    ).json()["access_token"]
    rep_headers = {"Authorization": f"Bearer {rep_token}"}

    blocked = await client.post(
        f"{API}/users/invite",
        headers=rep_headers,
        json={"email": _new_email(), "role": "rep"},
    )
    assert blocked.status_code == 403


async def test_list_users(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    await client.post(
        f"{API}/users/invite",
        headers=ws.headers,
        json={"email": _new_email(), "role": "rep"},
    )
    resp = await client.get(f"{API}/users", headers=ws.headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 2


async def test_update_role(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    invited = await client.post(
        f"{API}/users/invite",
        headers=ws.headers,
        json={"email": _new_email(), "role": "rep"},
    )
    user_id = invited.json()["user"]["id"]

    patched = await client.patch(
        f"{API}/users/{user_id}", headers=ws.headers, json={"role": "manager"}
    )
    assert patched.status_code == 200
    assert patched.json()["role"] == "manager"


async def test_admin_cannot_deactivate_self(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    me = (await client.get("/auth/me", headers=ws.headers)).json()
    resp = await client.delete(f"{API}/users/{me['id']}", headers=ws.headers)
    assert resp.status_code == 400


async def test_admin_can_deactivate_other(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    invited = await client.post(
        f"{API}/users/invite",
        headers=ws.headers,
        json={"email": _new_email(), "role": "rep"},
    )
    user_id = invited.json()["user"]["id"]
    resp = await client.delete(f"{API}/users/{user_id}", headers=ws.headers)
    assert resp.status_code == 204
