"""Test helpers — register a workspace and return its auth headers."""

from dataclasses import dataclass
from uuid import uuid4

from httpx import AsyncClient


@dataclass
class WorkspaceFixture:
    """A registered workspace + first-user admin auth context."""

    workspace_slug: str
    workspace_name: str
    user_email: str
    access_token: str
    headers: dict[str, str]


async def register_workspace(
    client: AsyncClient,
    *,
    slug_prefix: str = "ws",
    name: str | None = None,
) -> WorkspaceFixture:
    """Register a fresh workspace + admin user, returning auth headers."""
    suffix = uuid4().hex[:8]
    slug = f"{slug_prefix}-{suffix}"
    user_email = f"{suffix}@example.com"
    workspace_name = name or f"Workspace {suffix}"

    resp = await client.post(
        "/auth/register",
        json={
            "email": user_email,
            "password": "correct-horse-battery-staple",
            "first_name": "Test",
            "last_name": "User",
            "workspace_name": workspace_name,
            "workspace_slug": slug,
        },
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return WorkspaceFixture(
        workspace_slug=slug,
        workspace_name=workspace_name,
        user_email=user_email,
        access_token=token,
        headers={"Authorization": f"Bearer {token}"},
    )
