"""AI draft approval workflow tests.

External Anthropic calls fall through to the mock-mode response when no API
key is set (CI default). External email sends fall through to mock-mode in
the email_service when no Resend key is set, so approve flows commit cleanly
without making real HTTP calls.
"""

import uuid

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def _new_contact(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/contacts",
        headers=headers,
        json={"email": f"c-{uuid.uuid4().hex[:6]}@example.com"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_thread(
    client: AsyncClient, headers: dict[str, str], *, contact_id: str
) -> str:
    resp = await client.post(
        f"{API}/inbox/threads",
        headers=headers,
        json={
            "subject": f"Q-{uuid.uuid4().hex[:6]}",
            "to_emails": [contact_id + "@example.com"],
            "body_text": "Hello",
            "contact_id": contact_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _draft_outreach(
    client: AsyncClient, headers: dict[str, str], *, contact_id: str
) -> str:
    resp = await client.post(
        f"{API}/agents/contacts/{contact_id}/draft-outreach",
        headers=headers,
        json={},
    )
    assert resp.status_code == 201, resp.text
    drafts = await client.get(
        f"{API}/drafts?draft_type=outbound_email&entity_id={contact_id}",
        headers=headers,
    )
    assert drafts.status_code == 200
    items = drafts.json()["items"]
    assert items
    return items[0]["id"]


async def _draft_reply(
    client: AsyncClient, headers: dict[str, str], *, thread_id: str
) -> str:
    resp = await client.post(
        f"{API}/agents/threads/{thread_id}/draft-reply", headers=headers
    )
    assert resp.status_code == 201, resp.text
    drafts = await client.get(
        f"{API}/drafts?draft_type=email_reply&entity_id={thread_id}",
        headers=headers,
    )
    assert drafts.status_code == 200
    items = drafts.json()["items"]
    assert items
    return items[0]["id"]


async def test_list_pending_drafts_filters(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    await _draft_outreach(client, ws.headers, contact_id=contact_id)

    listed = await client.get(f"{API}/drafts", headers=ws.headers)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items
    assert all(d["status"] == "pending" for d in items)


async def test_approve_outbound_draft_sends_and_marks_approved(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    draft_id = await _draft_outreach(client, ws.headers, contact_id=contact_id)

    resp = await client.post(
        f"{API}/drafts/{draft_id}/approve", headers=ws.headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "approved"
    assert body["reviewed_at"] is not None
    assert body["reviewed_by_id"] is not None


async def test_edit_and_send_persists_edits(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    draft_id = await _draft_outreach(client, ws.headers, contact_id=contact_id)

    resp = await client.post(
        f"{API}/drafts/{draft_id}/edit-and-send",
        headers=ws.headers,
        json={
            "subject": "Edited subject",
            "body_text": "Edited body",
            "body_html": "<p>Edited body</p>",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "edited_and_sent"
    assert body["subject"] == "Edited subject"
    assert body["body_text"] == "Edited body"
    assert body["body_html"] == "<p>Edited body</p>"


async def test_discard_draft(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    draft_id = await _draft_outreach(client, ws.headers, contact_id=contact_id)

    resp = await client.post(
        f"{API}/drafts/{draft_id}/discard", headers=ws.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "discarded"


async def test_cannot_approve_twice(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    draft_id = await _draft_outreach(client, ws.headers, contact_id=contact_id)

    first = await client.post(
        f"{API}/drafts/{draft_id}/approve", headers=ws.headers
    )
    assert first.status_code == 200

    second = await client.post(
        f"{API}/drafts/{draft_id}/approve", headers=ws.headers
    )
    assert second.status_code == 409


async def test_approve_reply_draft_sends_on_thread(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    thread_id = await _new_thread(client, ws.headers, contact_id=contact_id)
    draft_id = await _draft_reply(client, ws.headers, thread_id=thread_id)

    resp = await client.post(
        f"{API}/drafts/{draft_id}/approve", headers=ws.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


async def test_drafts_workspace_isolation(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="dr-a")
    ws_b = await register_workspace(client, slug_prefix="dr-b")
    contact_id = await _new_contact(client, ws_a.headers)
    draft_id = await _draft_outreach(client, ws_a.headers, contact_id=contact_id)

    cross_get = await client.get(
        f"{API}/drafts/{draft_id}", headers=ws_b.headers
    )
    assert cross_get.status_code == 404

    cross_list = await client.get(f"{API}/drafts", headers=ws_b.headers)
    assert cross_list.status_code == 200
    assert cross_list.json()["items"] == []
