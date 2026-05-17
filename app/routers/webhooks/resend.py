"""Resend webhook handlers — email.delivered, opened, clicked, bounced events.

Resend signs each webhook with an HMAC-SHA256 of the raw request body using
the `RESEND_WEBHOOK_SECRET`. In dev mode (no secret configured), validation
accepts everything so the rest of the pipeline can be tested.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select, update

from app.dependencies import DbSession
from app.models.contact import Contact, EmailStatus
from app.models.message import Message
from app.services.email_service import validate_resend_signature

router = APIRouter(prefix="/webhooks/resend", tags=["webhooks"])


def _parse_event_time(raw: str | None) -> datetime:
    if raw is None:
        return datetime.now(UTC)
    try:
        # ISO 8601, allow trailing Z
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


@router.post("")
async def resend_event(
    request: Request,
    db: DbSession,
    resend_signature: str | None = Header(
        default=None, alias="resend-signature"
    ),
    svix_signature: str | None = Header(default=None, alias="svix-signature"),
) -> dict[str, str]:
    body = await request.body()
    signature = resend_signature or svix_signature
    if not validate_resend_signature(body=body, signature=signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Resend signature",
        )

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON"
        ) from exc

    event_type = payload.get("type") or payload.get("event")
    data = payload.get("data") or {}
    email_id = data.get("email_id") or data.get("id")
    if email_id is None:
        return {"status": "ignored", "reason": "missing email_id"}

    result = await db.execute(
        select(Message).where(Message.resend_message_id == email_id)
    )
    message = result.scalar_one_or_none()
    if message is None:
        return {"status": "ignored", "reason": "unknown message"}

    when = _parse_event_time(payload.get("created_at") or data.get("created_at"))

    if event_type == "email.delivered":
        if message.sent_at is None:
            message.sent_at = when
    elif event_type == "email.opened":
        if message.opened_at is None:
            message.opened_at = when
    elif event_type == "email.clicked":
        if message.clicked_at is None:
            message.clicked_at = when
    elif event_type == "email.bounced":
        recipients = message.to_emails or []
        if recipients:
            await db.execute(
                update(Contact)
                .where(
                    Contact.workspace_id == message.workspace_id,
                    Contact.email.in_(recipients),
                )
                .values(email_status=EmailStatus.BOUNCED)
            )

    await db.commit()
    return {"status": "ok", "event": event_type or "unknown"}
