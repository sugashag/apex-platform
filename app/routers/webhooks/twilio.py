"""Twilio webhook handlers — voice + SMS callbacks.

Twilio posts `application/x-www-form-urlencoded` payloads and signs each
request with `X-Twilio-Signature`. We validate the signature on every
request (dev mode accepts everything when no auth token is configured).

These endpoints don't require JWT auth — they're called by Twilio, not by
authenticated users. The workspace is resolved by phone-number lookup.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy import select

from app.dependencies import DbSession
from app.models.activity import Activity, ActivityType, ActorType
from app.models.call import Call, CallDirection, CallStatus
from app.models.contact import Contact
from app.models.sms_message import SmsDirection, SmsMessage, SmsStatus
from app.models.workspace import Workspace
from app.services import workflow_engine
from app.services.agent_queue import enqueue
from app.services.twilio_service import twilio_service

router = APIRouter(prefix="/webhooks/twilio", tags=["webhooks"])


_TWILIO_STATUS_MAP = {
    "queued": CallStatus.INITIATED,
    "initiated": CallStatus.INITIATED,
    "ringing": CallStatus.RINGING,
    "in-progress": CallStatus.IN_PROGRESS,
    "completed": CallStatus.COMPLETED,
    "failed": CallStatus.FAILED,
    "no-answer": CallStatus.NO_ANSWER,
    "busy": CallStatus.BUSY,
    "canceled": CallStatus.CANCELED,
}


async def _validate_request(
    request: Request, signature: str | None
) -> dict[str, str]:
    """Read form params + validate Twilio signature; raise 403 on failure."""
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    url = str(request.url)
    if not twilio_service.validate_webhook(url, params, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature",
        )
    return params


async def _resolve_workspace(
    db: DbSession, *, workspace_id_hint: str | None
) -> Workspace | None:
    """Pick the workspace for an inbound message/call.

    Real production routing would map the `To` number to a workspace, but
    that mapping is out of scope for Phase 2. For now we accept an explicit
    `workspace_id` query string (set by the Twilio number's webhook URL when
    you provision it per-workspace) and fall back to the only workspace in
    the system for single-tenant dev/test setups.
    """
    if workspace_id_hint is not None:
        try:
            from uuid import UUID as _UUID

            ws_id = _UUID(workspace_id_hint)
        except ValueError:
            ws_id = None
        if ws_id is not None:
            result = await db.execute(
                select(Workspace).where(Workspace.id == ws_id)
            )
            ws = result.scalar_one_or_none()
            if ws is not None:
                return ws

    all_ws = await db.execute(select(Workspace).limit(2))
    rows = list(all_ws.scalars().all())
    return rows[0] if len(rows) == 1 else None


@router.post("/voice/inbound")
async def voice_inbound(
    request: Request,
    db: DbSession,
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
) -> Response:
    """Inbound call — respond with TwiML to route to a softphone or voicemail."""
    params = await _validate_request(request, x_twilio_signature)

    workspace = await _resolve_workspace(
        db, workspace_id_hint=request.query_params.get("workspace_id")
    )
    if workspace is not None:
        from_number = params.get("From")
        contact: Contact | None = None
        if from_number is not None:
            c_result = await db.execute(
                select(Contact).where(
                    Contact.workspace_id == workspace.id,
                    Contact.phone == from_number,
                )
            )
            contact = c_result.scalar_one_or_none()

        call = Call(
            workspace_id=workspace.id,
            contact_id=contact.id if contact is not None else None,
            twilio_call_sid=params.get("CallSid"),
            direction=CallDirection.INBOUND,
            status=CallStatus.RINGING,
            from_number=from_number,
            to_number=params.get("To"),
            started_at=datetime.now(UTC),
        )
        db.add(call)
        await db.commit()

    twiml = twilio_service.generate_twiml_voicemail()
    return Response(content=twiml, media_type="application/xml")


@router.post("/voice/status")
async def voice_status(
    request: Request,
    db: DbSession,
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
) -> dict[str, str]:
    params = await _validate_request(request, x_twilio_signature)
    call_sid = params.get("CallSid")
    if call_sid is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing CallSid"
        )

    result = await db.execute(
        select(Call).where(Call.twilio_call_sid == call_sid)
    )
    call = result.scalar_one_or_none()
    if call is None:
        return {"status": "ignored", "reason": "unknown call sid"}

    twilio_status = params.get("CallStatus", "").lower()
    if twilio_status in _TWILIO_STATUS_MAP:
        call.status = _TWILIO_STATUS_MAP[twilio_status]
    if (duration := params.get("CallDuration")) is not None:
        try:
            call.duration_seconds = int(duration)
        except ValueError:
            pass

    now = datetime.now(UTC)
    if call.status == CallStatus.COMPLETED:
        call.ended_at = now
        if call.contact_id is not None:
            duration_str = (
                f"{call.duration_seconds // 60:02d}:{call.duration_seconds % 60:02d}"
                if call.duration_seconds is not None
                else "0:00"
            )
            db.add(
                Activity(
                    workspace_id=call.workspace_id,
                    contact_id=call.contact_id,
                    deal_id=call.deal_id,
                    type=ActivityType.CALL,
                    actor_type=ActorType.HUMAN,
                    subject=f"{call.direction.value} call ({duration_str})",
                    body=call.transcript,
                    occurred_at=now,
                )
            )
        await workflow_engine.trigger_workflow(
            db,
            workspace_id=call.workspace_id,
            trigger_type="call_completed",
            entity_type="call",
            entity_id=call.id,
            context={
                "call_id": str(call.id),
                "contact_id": str(call.contact_id) if call.contact_id else None,
                "deal_id": str(call.deal_id) if call.deal_id else None,
                "call": {
                    "id": str(call.id),
                    "direction": call.direction.value,
                    "status": call.status.value,
                    "duration_seconds": call.duration_seconds,
                    "from_number": call.from_number,
                    "to_number": call.to_number,
                },
            },
        )
    await db.commit()
    return {"status": "ok"}


@router.post("/voice/recording")
async def voice_recording(
    request: Request,
    db: DbSession,
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
) -> dict[str, str]:
    params = await _validate_request(request, x_twilio_signature)
    call_sid = params.get("CallSid")
    if call_sid is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing CallSid"
        )

    result = await db.execute(
        select(Call).where(Call.twilio_call_sid == call_sid)
    )
    call = result.scalar_one_or_none()
    if call is None:
        return {"status": "ignored", "reason": "unknown call sid"}

    call.recording_url = params.get("RecordingUrl")
    call.recording_sid = params.get("RecordingSid")
    # Twilio may send a transcript in the same recording callback when
    # `transcribe="true"` is set on the recording verb.
    transcript = params.get("TranscriptionText")
    if transcript and not call.transcript:
        call.transcript = transcript
    await db.commit()

    if call.transcript and call.ai_summary is None:
        await enqueue(
            "run_call_summarizer",
            call.workspace_id,
            call.id,
            trigger="call_recording",
        )

    return {"status": "ok"}


@router.post("/sms/inbound")
async def sms_inbound(
    request: Request,
    db: DbSession,
    x_twilio_signature: str | None = Header(default=None, alias="X-Twilio-Signature"),
) -> Response:
    params = await _validate_request(request, x_twilio_signature)

    workspace = await _resolve_workspace(
        db, workspace_id_hint=request.query_params.get("workspace_id")
    )
    if workspace is None:
        # Respond with empty TwiML — Twilio expects a 200.
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
            media_type="application/xml",
        )

    from_number = params.get("From", "")
    body = params.get("Body", "")
    twilio_sid = params.get("MessageSid")

    contact: Contact | None = None
    if from_number:
        c_result = await db.execute(
            select(Contact).where(
                Contact.workspace_id == workspace.id,
                Contact.phone == from_number,
            )
        )
        contact = c_result.scalar_one_or_none()
        if contact is None:
            contact = Contact(
                workspace_id=workspace.id,
                email=f"sms-{from_number.replace('+', '')}@unknown.example",
                phone=from_number,
                source="inbound_sms",
            )
            db.add(contact)
            await db.flush()

    now = datetime.now(UTC)
    sms = SmsMessage(
        workspace_id=workspace.id,
        contact_id=contact.id if contact is not None else None,
        twilio_message_sid=twilio_sid,
        direction=SmsDirection.INBOUND,
        from_number=from_number,
        to_number=params.get("To", ""),
        body=body,
        status=SmsStatus.RECEIVED,
        sent_at=now,
    )
    db.add(sms)

    if contact is not None:
        db.add(
            Activity(
                workspace_id=workspace.id,
                contact_id=contact.id,
                type=ActivityType.SMS,
                actor_type=ActorType.HUMAN,
                subject=f"SMS from {from_number}",
                body=body,
                occurred_at=now,
            )
        )

    await db.commit()
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
        media_type="application/xml",
    )
