"""Twilio webhook handlers — inbound SMS, voice status, voice recording,
signature validation."""

import base64
import json
import uuid

import pytest
from httpx import AsyncClient

from app.services.twilio_service import twilio_service
from tests.helpers import register_workspace

API = "/api/v1"


def _workspace_id(access_token: str) -> str:
    """Extract workspace_id from the JWT (without verifying — tests only)."""
    payload_b64 = access_token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
    return str(payload["workspace_id"])


async def test_inbound_sms_creates_contact_and_record(
    client: AsyncClient,
) -> None:
    ws = await register_workspace(client)

    from_number = f"+1555{uuid.uuid4().int % 10**7:07d}"
    resp = await client.post(
        f"/webhooks/twilio/sms/inbound?workspace_id={_workspace_id(ws.access_token)}",
        data={
            "MessageSid": f"SM{uuid.uuid4().hex}",
            "From": from_number,
            "To": "+15558889999",
            "Body": "hello from sms",
        },
    )
    assert resp.status_code == 200, resp.text
    assert "<Response" in resp.text

    listed = await client.get(f"{API}/sms?direction=inbound", headers=ws.headers)
    assert listed.status_code == 200
    matched = [m for m in listed.json()["items"] if m["from_number"] == from_number]
    assert len(matched) == 1
    assert matched[0]["body"] == "hello from sms"
    assert matched[0]["contact_id"] is not None

    by_id = await client.get(
        f"{API}/contacts/{matched[0]['contact_id']}", headers=ws.headers
    )
    assert by_id.status_code == 200
    assert by_id.json()["phone"] == from_number
    assert by_id.json()["source"] == "inbound_sms"


async def test_voice_status_updates_call_record(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    created = await client.post(
        f"{API}/calls",
        headers=ws.headers,
        json={"to_number": "+15551112222", "from_number": "+15558889999"},
    )
    assert created.status_code == 201
    sid = created.json()["twilio_call_sid"]

    resp = await client.post(
        "/webhooks/twilio/voice/status",
        data={
            "CallSid": sid,
            "CallStatus": "completed",
            "CallDuration": "42",
        },
    )
    assert resp.status_code == 200

    fetched = await client.get(
        f"{API}/calls/{created.json()['id']}", headers=ws.headers
    )
    assert fetched.json()["status"] == "completed"
    assert fetched.json()["duration_seconds"] == 42
    assert fetched.json()["ended_at"] is not None


async def test_voice_recording_callback_stores_url(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    created = await client.post(
        f"{API}/calls",
        headers=ws.headers,
        json={"to_number": "+15551112222", "from_number": "+15558889999"},
    )
    sid = created.json()["twilio_call_sid"]

    rec_sid = f"RE{uuid.uuid4().hex}"
    resp = await client.post(
        "/webhooks/twilio/voice/recording",
        data={
            "CallSid": sid,
            "RecordingSid": rec_sid,
            "RecordingUrl": "https://api.twilio.com/recordings/test.wav",
        },
    )
    assert resp.status_code == 200

    fetched = await client.get(
        f"{API}/calls/{created.json()['id']}", headers=ws.headers
    )
    assert fetched.json()["recording_sid"] == rec_sid
    assert fetched.json()["recording_url"] == "https://api.twilio.com/recordings/test.wav"


async def test_signature_validation_rejects_invalid(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force `validate_webhook` to fail and verify the route returns 403."""
    monkeypatch.setattr(
        twilio_service,
        "validate_webhook",
        lambda url, params, signature: False,
    )

    resp = await client.post(
        "/webhooks/twilio/sms/inbound",
        data={
            "MessageSid": "SMbad",
            "From": "+15550000000",
            "To": "+15551111111",
            "Body": "x",
        },
        headers={"X-Twilio-Signature": "bogus"},
    )
    assert resp.status_code == 403
