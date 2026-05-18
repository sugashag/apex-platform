"""PostHog server-side webhook ingestion.

PostHog's "webhook destination" can forward analytics events to us. We
authenticate the delivery with a shared secret in the
``X-PostHog-Signature`` header (compared with ``hmac.compare_digest``).

Mapped events:
  - $pageview     → PageView + VisitorSession upsert
  - $identify     → Contact upsert + first_touch Attribution
  - form_submit   → process_form_submission
  - demo_booked   → Activity (NOTE) on the contact

The endpoint always returns 200 to keep PostHog's retry queue happy on
benign drops (unknown event types, missing session, etc.). Unrecoverable
errors are logged and surface in /webhooks/posthog responses as
``{"ok": false, "error": "..."}``.
"""

from __future__ import annotations

import hmac
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from app.config import settings
from app.dependencies import DbSession
from app.models.activity import Activity, ActivityType, ActorType
from app.models.attribution import TouchType
from app.models.page_view import PageView
from app.models.visitor_session import VisitorSession
from app.services.attribution_service import (
    create_attribution_from_session,
    resolve_first_touch,
)
from app.services.contacts import get_or_create_by_email
from app.services.tracking_service import (
    enqueue_lead_scorer_post_commit,
    process_form_submission,
    process_identify,
    resolve_workspace_by_token,
    upsert_session,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/posthog", tags=["webhooks"])


def _signature_ok(signature: str | None) -> bool:
    expected = settings.POSTHOG_WEBHOOK_SECRET
    if not expected:
        # Dev mode — accept everything so the pipeline is testable.
        return True
    if not signature:
        return False
    return hmac.compare_digest(signature, expected)


def _props(event: dict[str, Any]) -> dict[str, Any]:
    props = event.get("properties")
    return props if isinstance(props, dict) else {}


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.post("")
async def posthog_event(
    request: Request,
    db: DbSession,
    x_posthog_signature: str | None = Header(default=None, alias="X-PostHog-Signature"),
) -> dict[str, Any]:
    if not _signature_ok(x_posthog_signature):
        return {"ok": False, "error": "invalid_signature"}

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "invalid_json"}

    events = payload if isinstance(payload, list) else [payload]
    processed = 0
    skipped = 0

    for event in events:
        if not isinstance(event, dict):
            skipped += 1
            continue
        try:
            ok = await _dispatch_event(db, event)
            processed += 1 if ok else 0
            skipped += 0 if ok else 1
        except Exception:  # noqa: BLE001
            await db.rollback()
            logger.exception("posthog event dispatch failed")
            skipped += 1

    return {"ok": True, "processed": processed, "skipped": skipped}


async def _dispatch_event(db: DbSession, event: dict[str, Any]) -> bool:
    """Route a single PostHog event. Returns True if processed."""
    event_type = event.get("event") or event.get("type")
    props = _props(event)
    workspace_token = (
        props.get("apex_workspace_token")
        or props.get("workspace_token")
        or event.get("workspace_token")
    )
    if not isinstance(workspace_token, str):
        return False

    workspace = await resolve_workspace_by_token(db, workspace_token)
    if workspace is None:
        return False

    session_id = (
        props.get("session_id")
        or props.get("$session_id")
        or props.get("distinct_id")
        or event.get("distinct_id")
    )
    if not isinstance(session_id, str) or not session_id:
        return False

    if event_type == "$pageview":
        url = props.get("$current_url") or props.get("url") or ""
        if not isinstance(url, str):
            return False
        session, _ = await upsert_session(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            url=url,
            referrer=props.get("$referrer") or props.get("referrer"),
            utm_source=props.get("utm_source"),
            utm_medium=props.get("utm_medium"),
            utm_campaign=props.get("utm_campaign"),
            utm_content=props.get("utm_content"),
            utm_term=props.get("utm_term"),
            gclid=props.get("gclid"),
            fbclid=props.get("fbclid"),
        )
        db.add(
            PageView(
                workspace_id=workspace.id,
                session_id=session.id,
                url=url,
                referrer=props.get("$referrer") or props.get("referrer"),
                title=props.get("title") or props.get("$title"),
                occurred_at=_parse_ts(event.get("timestamp")) or datetime.now(UTC),
            )
        )
        await db.commit()
        return True

    if event_type == "$identify":
        email = props.get("email") or props.get("$email")
        if not isinstance(email, str) or "@" not in email:
            return False
        await process_identify(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            email=email.strip().lower(),
            first_name=props.get("first_name") or props.get("$first_name"),
            last_name=props.get("last_name") or props.get("$last_name"),
        )
        await db.commit()
        return True

    if event_type == "form_submit":
        form_id = props.get("form_id") or "posthog_form"
        form_data = props.get("form_data") if isinstance(props.get("form_data"), dict) else props
        result = await process_form_submission(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            form_id=str(form_id),
            form_data=dict(form_data),
            page_url=props.get("$current_url") or props.get("page_url"),
        )
        await db.commit()
        await enqueue_lead_scorer_post_commit(
            workspace.id, UUID(result["lead_id"])
        )
        return True

    if event_type == "demo_booked":
        email = props.get("email")
        if not isinstance(email, str) or "@" not in email:
            return False
        contact, _ = await get_or_create_by_email(
            db,
            workspace.id,
            email.strip().lower(),
            first_name=props.get("first_name"),
            last_name=props.get("last_name"),
        )
        # Make sure attribution exists so this conversion is countable.
        if await resolve_first_touch(db, workspace.id, contact.id) is None:
            session = await _find_session_by_external_id(
                db, workspace.id, session_id
            )
            await create_attribution_from_session(
                db,
                workspace_id=workspace.id,
                contact_id=contact.id,
                session=session,
                touch_type=TouchType.FIRST_TOUCH,
            )
        db.add(
            Activity(
                workspace_id=workspace.id,
                contact_id=contact.id,
                type=ActivityType.MEETING,
                actor_type=ActorType.HUMAN,
                subject="Demo booked",
                meta={"source": "posthog", "properties": props},
            )
        )
        await db.commit()
        return True

    return False


async def _find_session_by_external_id(
    db: DbSession, workspace_id: Any, session_id: str
) -> VisitorSession | None:
    """Locate a VisitorSession by the client-visible session_id string."""
    result = await db.execute(
        select(VisitorSession).where(
            VisitorSession.workspace_id == workspace_id,
            VisitorSession.session_id == session_id,
        )
    )
    return result.scalar_one_or_none()
