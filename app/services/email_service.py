"""Email sending + inbound processing via Resend.

When `RESEND_API_KEY` is unset the service runs in mock mode: outbound sends
return a synthetic message ID and no HTTP call is made. This keeps CI and
local dev runnable without real credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.activity import Activity, ActivityType, ActorType
from app.models.contact import Contact
from app.models.email_account import EmailAccount
from app.models.message import Message, MessageDirection
from app.models.thread import Thread
from app.services.contacts import get_or_create_by_email

logger = logging.getLogger(__name__)


class EmailService:
    """Resend-backed email service with a graceful dev-mode fallback."""

    def __init__(self) -> None:
        self._configured = bool(settings.RESEND_API_KEY)
        if self._configured:
            try:
                import resend

                resend.api_key = settings.RESEND_API_KEY
                self._resend: Any | None = resend
            except ImportError:
                logger.warning(
                    "resend package not installed; running email_service in mock mode"
                )
                self._resend = None
                self._configured = False
        else:
            self._resend = None

    @property
    def configured(self) -> bool:
        return self._configured

    async def send_message(
        self,
        db: AsyncSession,
        thread: Thread,
        *,
        body_text: str | None,
        body_html: str | None,
        from_account: EmailAccount | None,
        actor_id: UUID | None,
        to_emails: list[str],
        cc_emails: list[str] | None = None,
    ) -> Message:
        """Send an outbound email and create a Message + Activity record.

        Caller is responsible for committing the transaction.
        """
        from_email = (
            from_account.email_address
            if from_account is not None
            else (settings.RESEND_FROM_EMAIL or "no-reply@example.com")
        )
        from_name = from_account.display_name if from_account is not None else None
        subject = thread.subject or "(no subject)"

        resend_id: str | None = None
        if self._resend is not None:
            try:
                params = {
                    "from": (
                        f"{from_name} <{from_email}>" if from_name else from_email
                    ),
                    "to": to_emails,
                    "subject": subject,
                    "html": body_html or (body_text or ""),
                    "text": body_text or "",
                }
                if cc_emails:
                    params["cc"] = cc_emails
                response = self._resend.Emails.send(params)
                resend_id = response.get("id") if isinstance(response, dict) else None
            except Exception:  # noqa: BLE001 — log + degrade rather than fail
                logger.exception("resend send failed; falling back to mock id")

        if resend_id is None:
            resend_id = f"mock-{uuid.uuid4().hex}"

        now = datetime.now(UTC)

        message = Message(
            workspace_id=thread.workspace_id,
            thread_id=thread.id,
            from_email=from_email,
            from_name=from_name,
            to_emails=to_emails,
            cc_emails=cc_emails,
            direction=MessageDirection.OUTBOUND,
            body_text=body_text,
            body_html=body_html,
            resend_message_id=resend_id,
            sent_at=now,
        )
        db.add(message)

        # Stamp first-response on thread if this is the first outbound reply.
        if thread.first_responded_at is None:
            thread.first_responded_at = now

        if thread.contact_id is not None:
            db.add(
                Activity(
                    workspace_id=thread.workspace_id,
                    contact_id=thread.contact_id,
                    deal_id=thread.deal_id,
                    actor_id=actor_id,
                    type=ActivityType.EMAIL_SENT,
                    actor_type=(
                        ActorType.HUMAN if actor_id is not None else ActorType.AI_AGENT
                    ),
                    subject=subject,
                    body=body_text or body_html,
                    occurred_at=now,
                )
            )

        await db.flush()
        return message

    async def process_inbound(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID,
        from_email: str,
        from_name: str | None,
        to_emails: list[str],
        subject: str | None,
        body_text: str | None,
        body_html: str | None,
        external_message_id: str | None = None,
        external_thread_id: str | None = None,
        cc_emails: list[str] | None = None,
    ) -> tuple[Thread, Message, Contact]:
        """Process an inbound email: upsert contact, find/create thread, store message.

        Caller commits the transaction.
        """
        contact, _ = await get_or_create_by_email(
            db,
            workspace_id,
            from_email,
            first_name=(from_name or "").split(" ")[0] or None,
            source="inbound_email",
        )

        thread: Thread | None = None
        if external_thread_id is not None:
            result = await db.execute(
                select(Thread).where(
                    Thread.workspace_id == workspace_id,
                    Thread.external_thread_id == external_thread_id,
                )
            )
            thread = result.scalar_one_or_none()

        now = datetime.now(UTC)
        if thread is None:
            from datetime import timedelta

            thread = Thread(
                workspace_id=workspace_id,
                contact_id=contact.id,
                subject=subject,
                external_thread_id=external_thread_id,
                sla_first_response_due_at=now
                + timedelta(minutes=settings.SLA_FIRST_RESPONSE_MINUTES),
                sla_resolution_due_at=now
                + timedelta(minutes=settings.SLA_RESOLUTION_MINUTES),
            )
            db.add(thread)
            await db.flush()

        message = Message(
            workspace_id=workspace_id,
            thread_id=thread.id,
            from_email=from_email,
            from_name=from_name,
            to_emails=to_emails,
            cc_emails=cc_emails,
            direction=MessageDirection.INBOUND,
            body_text=body_text,
            body_html=body_html,
            external_message_id=external_message_id,
            sent_at=now,
        )
        db.add(message)

        db.add(
            Activity(
                workspace_id=workspace_id,
                contact_id=contact.id,
                type=ActivityType.EMAIL_RECEIVED,
                actor_type=ActorType.HUMAN,
                subject=subject,
                body=body_text or body_html,
                occurred_at=now,
            )
        )

        await db.flush()
        return thread, message, contact


def validate_resend_signature(
    *,
    body: bytes,
    signature: str | None,
) -> bool:
    """Verify Resend webhook signature using `RESEND_WEBHOOK_SECRET`.

    Dev mode (no secret configured) accepts everything.
    """
    if not settings.RESEND_WEBHOOK_SECRET:
        return True
    if signature is None:
        return False

    expected = hmac.new(
        settings.RESEND_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    # Resend prefixes with `sha256=` in some versions; accept either form.
    candidate = signature.replace("sha256=", "").strip()
    return hmac.compare_digest(expected, candidate)


email_service = EmailService()
