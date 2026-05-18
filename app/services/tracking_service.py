"""Tracking services — session lifecycle, form processing, snippet builder."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity, ActivityType, ActorType
from app.models.attribution import TouchType
from app.models.contact import Contact
from app.models.form_submission import FormSubmission
from app.models.lead import Lead, LeadStatus
from app.models.visitor_session import VisitorSession
from app.models.workspace import Workspace
from app.services import workflow_engine
from app.services.agent_queue import enqueue
from app.services.attribution_service import (
    create_attribution_from_session,
    resolve_first_touch,
)
from app.services.contacts import get_or_create_by_email

logger = logging.getLogger(__name__)


async def resolve_workspace_by_token(
    db: AsyncSession, tracking_token: str
) -> Workspace | None:
    """Look up the workspace owning a public tracking_token."""
    if not tracking_token:
        return None
    result = await db.execute(
        select(Workspace).where(
            Workspace.tracking_token == tracking_token,
            Workspace.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def upsert_session(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    session_id: str,
    url: str | None = None,
    referrer: str | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
    utm_content: str | None = None,
    utm_term: str | None = None,
    gclid: str | None = None,
    fbclid: str | None = None,
) -> tuple[VisitorSession, bool]:
    """Find-or-create a VisitorSession. Returns (session, is_new).

    On first creation, UTM/click-id values are captured and frozen — later
    pageviews on the same session never overwrite them so attribution sticks
    to the first known origin.
    """
    result = await db.execute(
        select(VisitorSession).where(
            VisitorSession.workspace_id == workspace_id,
            VisitorSession.session_id == session_id,
        )
    )
    existing = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if existing is not None:
        existing.last_seen_at = now
        existing.page_count = (existing.page_count or 0) + 1
        await db.flush()
        return existing, False

    session = VisitorSession(
        workspace_id=workspace_id,
        session_id=session_id,
        ip_address=ip_address,
        user_agent=user_agent,
        source=_derive_source(utm_source, gclid, fbclid, referrer),
        campaign=utm_campaign,
        medium=utm_medium,
        content=utm_content,
        term=utm_term,
        landing_page_url=url,
        referrer_url=referrer,
        gclid=gclid,
        fbclid=fbclid,
        first_seen_at=now,
        last_seen_at=now,
        page_count=1,
    )
    db.add(session)
    await db.flush()
    return session, True


def _derive_source(
    utm_source: str | None,
    gclid: str | None,
    fbclid: str | None,
    referrer: str | None,
) -> str | None:
    """Pick the best-known source string for a session.

    Precedence: explicit utm_source > click-id (gclid/fbclid) > referrer-host
    heuristic > None (will surface as 'unknown' in reports).
    """
    if utm_source:
        return utm_source
    if gclid:
        return "google_ads"
    if fbclid:
        return "facebook_ads"
    if referrer:
        ref = referrer.lower()
        if "google." in ref:
            return "organic_search"
        if "linkedin." in ref:
            return "linkedin"
        if "facebook." in ref or "fb.com" in ref:
            return "facebook"
        return "referral"
    return "direct"


async def process_identify(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    session_id: str,
    email: str,
    first_name: str | None = None,
    last_name: str | None = None,
) -> Contact:
    """Link an anonymous VisitorSession to a known Contact.

    Creates the Contact if it doesn't exist, applies the session's UTM data
    onto Contact.source_* if those fields are empty, ensures a first_touch
    Attribution exists. Caller commits.
    """
    session = await _find_session(db, workspace_id, session_id)

    contact, _ = await get_or_create_by_email(
        db,
        workspace_id,
        email,
        first_name=first_name,
        last_name=last_name,
    )

    if first_name and not contact.first_name:
        contact.first_name = first_name
    if last_name and not contact.last_name:
        contact.last_name = last_name

    if session is not None:
        session.contact_id = contact.id
        _apply_session_to_contact(contact, session)

    existing_first_touch = await resolve_first_touch(db, workspace_id, contact.id)
    if existing_first_touch is None:
        await create_attribution_from_session(
            db,
            workspace_id=workspace_id,
            contact_id=contact.id,
            session=session,
            touch_type=TouchType.FIRST_TOUCH,
        )
    await db.flush()
    return contact


async def _find_session(
    db: AsyncSession, workspace_id: UUID, session_id: str | None
) -> VisitorSession | None:
    if not session_id:
        return None
    result = await db.execute(
        select(VisitorSession).where(
            VisitorSession.workspace_id == workspace_id,
            VisitorSession.session_id == session_id,
        )
    )
    return result.scalar_one_or_none()


def _apply_session_to_contact(contact: Contact, session: VisitorSession) -> None:
    """Backfill Contact.source_* with session values when the contact has none."""
    if contact.source is None and session.source is not None:
        contact.source = session.source
    if contact.source_campaign is None and session.campaign is not None:
        contact.source_campaign = session.campaign
    if contact.source_medium is None and session.medium is not None:
        contact.source_medium = session.medium
    if contact.source_term is None and session.term is not None:
        contact.source_term = session.term
    if contact.source_content is None and session.content is not None:
        contact.source_content = session.content
    if contact.first_seen_at is None:
        contact.first_seen_at = session.first_seen_at


async def process_form_submission(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    session_id: str | None,
    form_id: str,
    form_data: dict[str, Any],
    page_url: str | None = None,
) -> dict[str, Any]:
    """Main handler for marketing-site form submissions.

    Steps (all in the caller's transaction; caller commits at the end):
        1. Resolve VisitorSession (if any).
        2. Find or create the Contact from form_data['email'].
        3. Apply session UTM data onto Contact.source_* (if blank).
        4. Create a Lead with status='new' (skipped if one already exists).
        5. Create a first_touch Attribution if none exists.
        6. Persist a FormSubmission record.
        7. Create a 'note' Activity referencing the form.
        8. Best-effort enqueue the lead_scorer.
    Returns: ``{ contact_id, lead_id, success: True }``.
    """
    email = (form_data.get("email") or "").strip().lower()
    if not email:
        raise ValueError("form_data must include 'email'")

    session = await _find_session(db, workspace_id, session_id)

    first_name = form_data.get("first_name") or form_data.get("firstName")
    last_name = form_data.get("last_name") or form_data.get("lastName")
    phone = form_data.get("phone")

    contact, _ = await get_or_create_by_email(
        db,
        workspace_id,
        email,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
    )
    if first_name and not contact.first_name:
        contact.first_name = first_name
    if last_name and not contact.last_name:
        contact.last_name = last_name
    if phone and not contact.phone:
        contact.phone = phone

    if session is not None:
        session.contact_id = contact.id
        _apply_session_to_contact(contact, session)
    elif contact.source is None:
        contact.source = "direct"

    # 4. Reuse existing un-converted Lead if present, otherwise create one.
    existing_lead_result = await db.execute(
        select(Lead).where(
            Lead.workspace_id == workspace_id,
            Lead.contact_id == contact.id,
            Lead.status != LeadStatus.CONVERTED,
        )
    )
    lead = existing_lead_result.scalars().first()
    if lead is None:
        lead = Lead(
            workspace_id=workspace_id,
            contact_id=contact.id,
            status=LeadStatus.NEW,
            source=contact.source,
        )
        db.add(lead)
        await db.flush()

    # 5. First-touch Attribution.
    existing_first_touch = await resolve_first_touch(db, workspace_id, contact.id)
    if existing_first_touch is None:
        await create_attribution_from_session(
            db,
            workspace_id=workspace_id,
            contact_id=contact.id,
            session=session,
            touch_type=TouchType.FIRST_TOUCH,
        )

    # 6. Persist the raw submission for replay/forensics.
    submission = FormSubmission(
        workspace_id=workspace_id,
        contact_id=contact.id,
        session_id=session.id if session is not None else None,
        form_id=form_id,
        form_data=form_data,
        page_url=page_url,
        processed_at=datetime.now(UTC),
    )
    db.add(submission)

    # 7. Timeline note.
    db.add(
        Activity(
            workspace_id=workspace_id,
            contact_id=contact.id,
            lead_id=lead.id,
            type=ActivityType.NOTE,
            actor_type=ActorType.HUMAN,
            subject=f"Form submitted: {form_id}",
            body=None,
            meta={
                "form_id": form_id,
                "form_data": form_data,
                "page_url": page_url,
            },
        )
    )

    await db.flush()

    await workflow_engine.trigger_workflow(
        db,
        workspace_id=workspace_id,
        trigger_type="form_submitted",
        entity_type="contact",
        entity_id=contact.id,
        context={
            "contact_id": str(contact.id),
            "lead_id": str(lead.id),
            "form_id": form_id,
            "form_data": form_data,
            "contact": {
                "id": str(contact.id),
                "email": contact.email,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "source": contact.source,
            },
        },
    )

    return {
        "contact_id": str(contact.id),
        "lead_id": str(lead.id),
        "success": True,
    }


async def enqueue_lead_scorer_post_commit(
    workspace_id: UUID, lead_id: UUID
) -> None:
    """Best-effort lead-scorer enqueue. Call AFTER the DB transaction commits
    so the worker never sees an orphaned lead_id."""
    try:
        await enqueue(
            "run_lead_scorer",
            workspace_id,
            lead_id,
            trigger="form_submission",
        )
    except Exception:  # noqa: BLE001
        logger.exception("lead_scorer enqueue failed for lead %s", lead_id)


# --- snippet builder --------------------------------------------------------


def build_tracking_snippet(*, tracking_token: str, api_base_url: str) -> str:
    """Build the marketing-site JS snippet for a workspace.

    The snippet:
      - Generates / restores a session_id in localStorage.
      - Parses UTM params + gclid/fbclid on first landing and posts /track/session.
      - Sends a /track/pageview for the initial pageview.
      - Intercepts forms with `data-apex-form="<form_id>"` and posts /track/form.
      - Exposes window.apex.identify(email, fields) for post-login identity.

    The token is embedded in plain text — it's a public read-only credential,
    not a JWT. Rate limiting + server-side validation guard the endpoints.
    """
    return _SNIPPET_TEMPLATE.format(
        tracking_token=tracking_token,
        api_base_url=api_base_url.rstrip("/"),
    )


_SNIPPET_TEMPLATE = """\
<!-- APEX Analytics — paste before </body> -->
<script>
(function () {{
  var APEX_TOKEN = '{tracking_token}';
  var APEX_URL = '{api_base_url}';
  var SESSION_KEY = 'apex_session_id';
  var sid = null;
  try {{ sid = localStorage.getItem(SESSION_KEY); }} catch (e) {{}}
  if (!sid) {{
    sid = (crypto && crypto.randomUUID)
      ? crypto.randomUUID()
      : ('s-' + Date.now() + '-' + Math.random().toString(36).slice(2));
    try {{ localStorage.setItem(SESSION_KEY, sid); }} catch (e) {{}}
  }}

  var qs = new URLSearchParams(window.location.search);
  function send(path, body) {{
    return fetch(APEX_URL + path, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(body),
      keepalive: true
    }}).catch(function () {{ /* never break the host page */ }});
  }}

  send('/track/session', {{
    session_id: sid,
    workspace_token: APEX_TOKEN,
    url: window.location.href,
    referrer: document.referrer || null,
    utm_source:   qs.get('utm_source'),
    utm_medium:   qs.get('utm_medium'),
    utm_campaign: qs.get('utm_campaign'),
    utm_content:  qs.get('utm_content'),
    utm_term:     qs.get('utm_term'),
    gclid:  qs.get('gclid'),
    fbclid: qs.get('fbclid'),
    user_agent: navigator.userAgent
  }});

  send('/track/pageview', {{
    session_id: sid,
    workspace_token: APEX_TOKEN,
    url: window.location.href,
    referrer: document.referrer || null,
    title: document.title
  }});

  document.addEventListener('submit', function (ev) {{
    var form = ev.target;
    if (!form || !form.matches || !form.matches('[data-apex-form]')) return;
    var formId = form.getAttribute('data-apex-form');
    var data = {{}};
    Array.prototype.forEach.call(form.elements, function (el) {{
      if (el.name) data[el.name] = el.value;
    }});
    send('/track/form', {{
      session_id: sid,
      workspace_token: APEX_TOKEN,
      form_id: formId,
      form_data: data,
      page_url: window.location.href
    }});
  }}, true);

  window.apex = window.apex || {{}};
  window.apex.identify = function (email, fields) {{
    fields = fields || {{}};
    return send('/track/identify', {{
      session_id: sid,
      workspace_token: APEX_TOKEN,
      email: email,
      first_name: fields.first_name || null,
      last_name: fields.last_name || null
    }});
  }};
}})();
</script>
"""
