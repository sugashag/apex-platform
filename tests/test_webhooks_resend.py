"""Resend webhook event handling — opened/clicked/bounced."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.services import email_service as email_service_module
from tests.helpers import register_workspace

API = "/api/v1"


async def _create_thread_message(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[str, str, str]:
    """Compose a new outbound thread, then return (thread_id, message_id, resend_id)."""
    contact_resp = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={"email": f"c-{uuid.uuid4().hex[:6]}@example.com"},
    )
    contact_id = contact_resp.json()["id"]

    target_email = f"target-{uuid.uuid4().hex[:6]}@example.com"
    compose = await client.post(
        f"{API}/inbox/threads",
        headers=headers,
        json={
            "subject": "hi",
            "to_emails": [target_email],
            "body_text": "hello",
            "contact_id": contact_id,
        },
    )
    assert compose.status_code == 201, compose.text
    body = compose.json()
    thread_id = body["id"]
    msg = body["messages"][0]
    return thread_id, msg["id"], msg["resend_message_id"]


async def test_email_opened_event_updates_message(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    _, msg_id, resend_id = await _create_thread_message(client, ws.headers)

    resp = await client.post(
        "/webhooks/resend",
        json={
            "type": "email.opened",
            "created_at": datetime.now(UTC).isoformat(),
            "data": {"email_id": resend_id},
        },
    )
    assert resp.status_code == 200, resp.text

    fetched = await client.get(f"{API}/messages/{msg_id}", headers=ws.headers)
    assert fetched.json()["opened_at"] is not None


async def test_email_clicked_event_updates_message(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    _, msg_id, resend_id = await _create_thread_message(client, ws.headers)

    resp = await client.post(
        "/webhooks/resend",
        json={
            "type": "email.clicked",
            "data": {"email_id": resend_id},
        },
    )
    assert resp.status_code == 200

    fetched = await client.get(f"{API}/messages/{msg_id}", headers=ws.headers)
    assert fetched.json()["clicked_at"] is not None


async def test_email_bounced_marks_contact_bounced(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    # Use a recipient we can verify after — create a contact whose email matches
    # the outbound `to` recipient so we can assert the bounce flag was applied.
    target_email = f"bouncer-{uuid.uuid4().hex[:6]}@example.com"
    contact_resp = await client.post(
        f"{API}/contacts", headers=ws.headers, json={"email": target_email}
    )
    contact_id = contact_resp.json()["id"]

    compose = await client.post(
        f"{API}/inbox/threads",
        headers=ws.headers,
        json={
            "subject": "test",
            "to_emails": [target_email],
            "body_text": "hi",
            "contact_id": contact_id,
        },
    )
    assert compose.status_code == 201
    resend_id = compose.json()["messages"][0]["resend_message_id"]

    resp = await client.post(
        "/webhooks/resend",
        json={"type": "email.bounced", "data": {"email_id": resend_id}},
    )
    assert resp.status_code == 200

    fetched = await client.get(f"{API}/contacts/{contact_id}", headers=ws.headers)
    assert fetched.json()["email_status"] == "bounced"


async def test_resend_signature_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a webhook secret is configured, an unsigned request must be rejected."""
    monkeypatch.setattr(
        email_service_module,
        "validate_resend_signature",
        lambda *, body, signature: False,
    )
    # Also need to patch the import site in the router module.
    from app.routers.webhooks import resend as resend_router

    monkeypatch.setattr(
        resend_router,
        "validate_resend_signature",
        lambda *, body, signature: False,
    )

    resp = await client.post(
        "/webhooks/resend",
        json={"type": "email.opened", "data": {"email_id": "anything"}},
    )
    assert resp.status_code == 403
