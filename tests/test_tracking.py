"""Public /track/* endpoint tests.

These endpoints are unauthenticated (no JWT) — they're called by the marketing
site JS snippet. They must:
  - Authenticate via the per-workspace ``tracking_token``.
  - Never return 500 on bad input — always 200 with ``ok: false`` instead, so
    a broken backend doesn't take down the host marketing site.
  - Create the correct chain of Contact + Lead + Attribution + Activity
    records on form submission.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models.activity import Activity, ActivityType
from app.models.attribution import Attribution, TouchType
from app.models.contact import Contact
from app.models.form_submission import FormSubmission
from app.models.lead import Lead
from app.models.page_view import PageView
from app.models.visitor_session import VisitorSession
from app.models.workspace import Workspace
from app.routers.tracking import _rate_limiter
from tests.helpers import register_workspace


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """Every test starts with a clean rate-limit slate so we don't trip the
    100-req/min cap across the suite."""
    _rate_limiter.reset()


async def _workspace_token(client: AsyncClient) -> tuple[str, str]:
    """Register a workspace, return (workspace_id, tracking_token)."""
    ws = await register_workspace(client)
    async with SessionLocal() as session:
        result = await session.execute(
            select(Workspace).where(Workspace.slug == ws.workspace_slug)
        )
        workspace = result.scalar_one()
        assert workspace.tracking_token is not None, (
            "tracking_token should be auto-generated at registration"
        )
        return str(workspace.id), workspace.tracking_token


async def test_session_create_then_update_increments_page_count(
    client: AsyncClient,
) -> None:
    workspace_id, token = await _workspace_token(client)
    sid = f"sess-{uuid.uuid4().hex[:8]}"

    first = await client.post(
        "/track/session",
        json={
            "session_id": sid,
            "workspace_token": token,
            "url": "https://acme.com/?utm_source=google_ads&utm_campaign=spring",
            "referrer": "https://google.com/search?q=acme",
            "utm_source": "google_ads",
            "utm_campaign": "spring",
            "utm_medium": "cpc",
            "gclid": "Cj0KCQjwxxx",
        },
    )
    assert first.status_code == 200
    body = first.json()
    assert body["ok"] is True
    assert body["is_new"] is True

    second = await client.post(
        "/track/session",
        json={
            "session_id": sid,
            "workspace_token": token,
            "url": "https://acme.com/pricing",
        },
    )
    assert second.json()["is_new"] is False

    async with SessionLocal() as session:
        result = await session.execute(
            select(VisitorSession).where(
                VisitorSession.workspace_id == workspace_id,
                VisitorSession.session_id == sid,
            )
        )
        vs = result.scalar_one()
        assert vs.source == "google_ads"
        assert vs.campaign == "spring"
        assert vs.gclid == "Cj0KCQjwxxx"
        assert vs.page_count == 2


async def test_pageview_records_row(client: AsyncClient) -> None:
    workspace_id, token = await _workspace_token(client)
    sid = f"sess-{uuid.uuid4().hex[:8]}"

    await client.post(
        "/track/session",
        json={"session_id": sid, "workspace_token": token, "url": "https://acme.com/"},
    )
    resp = await client.post(
        "/track/pageview",
        json={
            "session_id": sid,
            "workspace_token": token,
            "url": "https://acme.com/pricing",
            "title": "Pricing — Acme",
            "time_on_page_seconds": 45,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    async with SessionLocal() as session:
        result = await session.execute(
            select(PageView).where(PageView.workspace_id == workspace_id)
        )
        rows = list(result.scalars().all())
        assert any(r.url == "https://acme.com/pricing" for r in rows)


async def test_bad_token_returns_200_with_error_flag_not_500(
    client: AsyncClient,
) -> None:
    """Endpoints must NEVER 500 — a broken token returns 200 + ok:false."""
    resp = await client.post(
        "/track/session",
        json={
            "session_id": "any",
            "workspace_token": "totally-bogus-token",
            "url": "https://x.com/",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "invalid_token"


async def test_form_submission_creates_contact_lead_attribution(
    client: AsyncClient,
) -> None:
    workspace_id, token = await _workspace_token(client)
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    email = f"lead-{uuid.uuid4().hex[:6]}@example.com"

    # First land on the site with UTMs so attribution has data.
    await client.post(
        "/track/session",
        json={
            "session_id": sid,
            "workspace_token": token,
            "url": "https://acme.com/?utm_source=google_ads&utm_campaign=spring",
            "utm_source": "google_ads",
            "utm_campaign": "spring",
            "utm_medium": "cpc",
        },
    )

    resp = await client.post(
        "/track/form",
        json={
            "session_id": sid,
            "workspace_token": token,
            "form_id": "demo_request",
            "form_data": {
                "email": email,
                "first_name": "Grace",
                "last_name": "Hopper",
                "company": "Acme",
            },
            "page_url": "https://acme.com/demo",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["success"] is True
    contact_id = body["contact_id"]
    lead_id = body["lead_id"]

    async with SessionLocal() as session:
        contact = (
            await session.execute(select(Contact).where(Contact.id == contact_id))
        ).scalar_one()
        assert contact.email == email
        assert contact.source == "google_ads"
        assert contact.source_campaign == "spring"

        lead = (
            await session.execute(select(Lead).where(Lead.id == lead_id))
        ).scalar_one()
        assert lead.contact_id == contact.id
        assert lead.source == "google_ads"

        attribution = (
            await session.execute(
                select(Attribution).where(
                    Attribution.contact_id == contact.id,
                    Attribution.touch_type == TouchType.FIRST_TOUCH,
                )
            )
        ).scalar_one()
        assert attribution.source == "google_ads"
        assert attribution.campaign == "spring"

        submission = (
            await session.execute(
                select(FormSubmission).where(FormSubmission.contact_id == contact.id)
            )
        ).scalar_one()
        assert submission.form_id == "demo_request"
        assert submission.form_data["email"] == email

        activity = (
            await session.execute(
                select(Activity).where(
                    Activity.contact_id == contact.id,
                    Activity.type == ActivityType.NOTE,
                )
            )
        ).scalar_one()
        assert "demo_request" in (activity.subject or "")


async def test_form_submission_without_email_returns_error_not_500(
    client: AsyncClient,
) -> None:
    _, token = await _workspace_token(client)
    resp = await client.post(
        "/track/form",
        json={
            "session_id": "sess-x",
            "workspace_token": token,
            "form_id": "newsletter",
            "form_data": {"first_name": "No"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


async def test_identify_links_session_and_creates_first_touch(
    client: AsyncClient,
) -> None:
    _, token = await _workspace_token(client)
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    email = f"id-{uuid.uuid4().hex[:6]}@example.com"

    await client.post(
        "/track/session",
        json={
            "session_id": sid,
            "workspace_token": token,
            "url": "https://acme.com/blog?utm_source=linkedin_ads",
            "utm_source": "linkedin_ads",
        },
    )

    resp = await client.post(
        "/track/identify",
        json={
            "session_id": sid,
            "workspace_token": token,
            "email": email,
            "first_name": "Ada",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    contact_id = body["contact_id"]

    async with SessionLocal() as session:
        vs = (
            await session.execute(
                select(VisitorSession).where(VisitorSession.session_id == sid)
            )
        ).scalar_one()
        assert vs.contact_id is not None
        assert str(vs.contact_id) == contact_id

        attr = (
            await session.execute(
                select(Attribution).where(Attribution.contact_id == contact_id)
            )
        ).scalar_one()
        assert attr.touch_type == TouchType.FIRST_TOUCH
        assert attr.source == "linkedin_ads"


async def test_pixel_returns_gif_even_for_bad_token(client: AsyncClient) -> None:
    resp = await client.get("/track/pixel/bogus-token")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/gif")
    # GIF magic bytes
    assert resp.content[:6] in (b"GIF87a", b"GIF89a")


async def test_tracking_snippet_endpoint_returns_token_and_js(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)

    me = await client.get("/auth/me", headers=ws.headers)
    workspace_id = me.json()["workspace_id"]

    resp = await client.get(
        f"/workspaces/{workspace_id}/tracking-snippet", headers=ws.headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tracking_token"]
    assert body["tracking_token"] in body["snippet"]
    assert "/track/session" in body["snippet"]
    assert "/track/form" in body["snippet"]


async def test_cross_workspace_snippet_access_denied(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="snip-a")
    ws_b = await register_workspace(client, slug_prefix="snip-b")

    me_a = await client.get("/auth/me", headers=ws_a.headers)
    workspace_a_id = me_a.json()["workspace_id"]

    resp = await client.get(
        f"/workspaces/{workspace_a_id}/tracking-snippet", headers=ws_b.headers
    )
    assert resp.status_code == 403
