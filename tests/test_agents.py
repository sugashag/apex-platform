"""AI agent endpoint tests.

External Anthropic calls are mocked at the service layer — `anthropic_service`
already degrades to a deterministic mock JSON response when `ANTHROPIC_API_KEY`
is unset (the default in CI), so no extra monkeypatching is required for the
happy paths.

The auto-trigger path (lead created → enqueue lead_scorer) uses ARQ; the
enqueue helper silently skips when Redis is unreachable, so we only assert
that creation does not crash and that the manual `/agents/leads/{id}/score`
endpoint produces the expected side effects.
"""

import uuid

import pytest
from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def _new_contact(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    company_id: str | None = None,
    title: str | None = "VP Engineering",
) -> str:
    payload: dict[str, object] = {
        "email": f"c-{uuid.uuid4().hex[:6]}@example.com",
        "first_name": "Pat",
        "last_name": "Smith",
        "title": title,
        "source": "google_ads",
    }
    if company_id:
        payload["company_id"] = company_id
    resp = await client.post(f"{API}/contacts", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_company(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        f"{API}/companies",
        headers=headers,
        json={
            "name": f"Acme-{uuid.uuid4().hex[:6]}",
            "domain": f"{uuid.uuid4().hex[:8]}.example.com",
            "industry": "SaaS",
            "employee_count": 250,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_lead(client: AsyncClient, headers: dict[str, str]) -> str:
    company_id = await _new_company(client, headers)
    contact_id = await _new_contact(client, headers, company_id=company_id)
    resp = await client.post(
        f"{API}/leads",
        headers=headers,
        json={"contact_id": contact_id, "source": "inbound"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------- lead scorer ------------------------------------------------------


async def test_lead_scorer_updates_score_and_writes_run(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    lead_id = await _new_lead(client, ws.headers)

    resp = await client.post(
        f"{API}/agents/leads/{lead_id}/score", headers=ws.headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["agent_type"] == "lead_scorer"
    assert body["status"] == "completed"
    assert body["entity_type"] == "lead"
    assert body["entity_id"] == lead_id
    assert body["input_tokens"] is not None and body["input_tokens"] > 0
    assert body["output_tokens"] is not None and body["output_tokens"] > 0
    assert body["latency_ms"] is not None
    assert body["model_used"] == "claude-opus-4-6"
    assert isinstance(body["output"], dict)
    assert "score" in body["output"]

    # Lead.score + rationale updated.
    lead_resp = await client.get(f"{API}/leads/{lead_id}", headers=ws.headers)
    assert lead_resp.status_code == 200
    lead = lead_resp.json()
    assert 0 <= lead["score"] <= 100
    assert lead["score_rationale"]

    # Score-update activity created.
    contact_id = lead["contact_id"]
    timeline = await client.get(
        f"{API}/contacts/{contact_id}/timeline", headers=ws.headers
    )
    assert timeline.status_code == 200
    types = [a["type"] for a in timeline.json()["items"]]
    assert "score_update" in types


async def test_lead_scorer_404_for_other_workspace(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="ag-a")
    ws_b = await register_workspace(client, slug_prefix="ag-b")
    lead_id = await _new_lead(client, ws_a.headers)

    resp = await client.post(
        f"{API}/agents/leads/{lead_id}/score", headers=ws_b.headers
    )
    assert resp.status_code == 404


async def test_create_lead_does_not_crash_when_redis_unavailable(
    client: AsyncClient,
) -> None:
    """The lead_created hook silently skips when Redis is unreachable."""
    ws = await register_workspace(client)
    company_id = await _new_company(client, ws.headers)
    contact_id = await _new_contact(client, ws.headers, company_id=company_id)
    resp = await client.post(
        f"{API}/leads",
        headers=ws.headers,
        json={"contact_id": contact_id, "source": "inbound"},
    )
    assert resp.status_code == 201, resp.text


# ---------- call summarizer --------------------------------------------------


async def _new_call_with_transcript(
    client: AsyncClient, headers: dict[str, str], *, contact_id: str
) -> str:
    created = await client.post(
        f"{API}/calls",
        headers=headers,
        json={
            "to_number": "+15551234567",
            "from_number": "+15559998888",
            "contact_id": contact_id,
        },
    )
    call_id = created.json()["id"]
    patched = await client.patch(
        f"{API}/calls/{call_id}",
        headers=headers,
        json={
            "duration_seconds": 320,
            "transcript": "Customer said pricing is too high but loves the product.",
        },
    )
    assert patched.status_code == 200
    return call_id


async def test_call_summarizer_writes_summary_and_run(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers, title="CTO")
    call_id = await _new_call_with_transcript(
        client, ws.headers, contact_id=contact_id
    )

    resp = await client.post(
        f"{API}/agents/calls/{call_id}/summarize", headers=ws.headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["agent_type"] == "call_summarizer"
    assert body["status"] == "completed"
    assert body["model_used"] == "claude-sonnet-4-6"
    assert "summary" in body["output"]

    # Call.ai_summary set.
    call_resp = await client.get(f"{API}/calls/{call_id}", headers=ws.headers)
    assert call_resp.status_code == 200
    call = call_resp.json()
    assert call["ai_summary"]
    # Sentiment is parsed from the mock ("neutral").
    assert call["ai_sentiment"] in {"positive", "neutral", "negative"}


async def test_call_summarizer_requires_transcript(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    created = await client.post(
        f"{API}/calls",
        headers=ws.headers,
        json={
            "to_number": "+15551234567",
            "from_number": "+15559998888",
            "contact_id": contact_id,
        },
    )
    call_id = created.json()["id"]
    resp = await client.post(
        f"{API}/agents/calls/{call_id}/summarize", headers=ws.headers
    )
    assert resp.status_code == 400


# ---------- outbound drafter -------------------------------------------------


async def test_outbound_drafter_creates_pending_draft(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    company_id = await _new_company(client, ws.headers)
    contact_id = await _new_contact(client, ws.headers, company_id=company_id)

    resp = await client.post(
        f"{API}/agents/contacts/{contact_id}/draft-outreach",
        headers=ws.headers,
        json={"step_instructions": "First touch, mention industry."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["agent_type"] == "outbound_drafter"
    assert body["status"] == "completed"

    drafts = await client.get(
        f"{API}/drafts?draft_type=outbound_email&entity_id={contact_id}",
        headers=ws.headers,
    )
    assert drafts.status_code == 200
    items = drafts.json()["items"]
    assert len(items) == 1
    draft = items[0]
    assert draft["status"] == "pending"
    assert draft["entity_type"] == "contact"
    assert draft["entity_id"] == contact_id
    assert draft["body_text"]
    # Nothing was auto-sent: contact has no outbound messages.


async def test_outbound_drafter_default_instructions(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    resp = await client.post(
        f"{API}/agents/contacts/{contact_id}/draft-outreach",
        headers=ws.headers,
        json={},
    )
    assert resp.status_code == 201, resp.text


# ---------- reply drafter ----------------------------------------------------


async def _new_thread(
    client: AsyncClient, headers: dict[str, str], *, contact_id: str
) -> str:
    resp = await client.post(
        f"{API}/inbox/threads",
        headers=headers,
        json={
            "subject": "Pricing question",
            "to_emails": [f"target-{uuid.uuid4().hex[:6]}@example.com"],
            "body_text": "Can you share enterprise pricing?",
            "contact_id": contact_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_reply_drafter_creates_pending_reply_draft(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)
    contact_id = await _new_contact(client, ws.headers)
    thread_id = await _new_thread(client, ws.headers, contact_id=contact_id)

    resp = await client.post(
        f"{API}/agents/threads/{thread_id}/draft-reply", headers=ws.headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["agent_type"] == "reply_drafter"
    assert body["status"] == "completed"

    drafts = await client.get(
        f"{API}/drafts?draft_type=email_reply&entity_id={thread_id}",
        headers=ws.headers,
    )
    assert drafts.status_code == 200
    items = drafts.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "pending"
    assert items[0]["entity_type"] == "thread"


# ---------- run listing ------------------------------------------------------


async def test_list_runs_filters_and_workspace_isolation(
    client: AsyncClient,
) -> None:
    ws_a = await register_workspace(client, slug_prefix="ag-list-a")
    ws_b = await register_workspace(client, slug_prefix="ag-list-b")
    lead_a = await _new_lead(client, ws_a.headers)
    await client.post(
        f"{API}/agents/leads/{lead_a}/score", headers=ws_a.headers
    )

    runs_a = await client.get(
        f"{API}/agents/runs?agent_type=lead_scorer&status=completed",
        headers=ws_a.headers,
    )
    assert runs_a.status_code == 200
    items_a = runs_a.json()["items"]
    assert items_a
    assert all(r["agent_type"] == "lead_scorer" for r in items_a)
    assert all(r["status"] == "completed" for r in items_a)

    # Workspace B cannot see workspace A's runs.
    runs_b = await client.get(f"{API}/agents/runs", headers=ws_b.headers)
    assert runs_b.status_code == 200
    assert runs_b.json()["items"] == []


async def test_get_run_404_other_workspace(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="ag-det-a")
    ws_b = await register_workspace(client, slug_prefix="ag-det-b")
    lead_id = await _new_lead(client, ws_a.headers)
    created = await client.post(
        f"{API}/agents/leads/{lead_id}/score", headers=ws_a.headers
    )
    run_id = created.json()["id"]

    cross = await client.get(
        f"{API}/agents/runs/{run_id}", headers=ws_b.headers
    )
    assert cross.status_code == 404


# ---------- agent failure path -----------------------------------------------


async def test_agent_failure_records_failed_status(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If Claude raises, the AgentRun is marked failed with an error message.

    The audit record lives in its own session so the failure survives the
    caller's rollback. The endpoint re-raises (so ASGI propagates), which
    is what we wrap in `pytest.raises` below.
    """
    import app.services.anthropic_service as svc

    async def boom(*args: object, **kwargs: object) -> tuple[str, int, int]:
        raise RuntimeError("simulated provider outage")

    monkeypatch.setattr(svc.anthropic_service, "complete", boom)

    ws = await register_workspace(client, slug_prefix="ag-fail")
    lead_id = await _new_lead(client, ws.headers)

    with pytest.raises(RuntimeError, match="simulated provider outage"):
        await client.post(
            f"{API}/agents/leads/{lead_id}/score", headers=ws.headers
        )

    runs = await client.get(
        f"{API}/agents/runs?agent_type=lead_scorer&status=failed",
        headers=ws.headers,
    )
    assert runs.status_code == 200
    items = runs.json()["items"]
    assert items
    assert items[0]["error_message"]
    assert "simulated provider outage" in items[0]["error_message"]
    assert items[0]["entity_id"] == lead_id
