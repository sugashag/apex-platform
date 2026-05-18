"""Public tracking endpoints — called by the marketing-site JS snippet.

NO JWT auth. These endpoints are reached cross-origin from the marketing
site and are protected by:
  - A public, per-workspace ``tracking_token`` that identifies the tenant.
  - An IP-based sliding-window rate limit (see TRACKING_RATE_LIMIT_PER_MINUTE).
  - Per-handler exception trapping — endpoints return HTTP 200 with
    ``{"ok": false, "error": "..."}`` rather than 500, so a broken backend
    never breaks the host site's form submission.
"""

from __future__ import annotations

import base64
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.dependencies import DbSession
from app.models.page_view import PageView
from app.services.tracking_service import (
    enqueue_lead_scorer_post_commit,
    process_form_submission,
    process_identify,
    resolve_workspace_by_token,
    upsert_session,
)
from app.utils.rate_limit import InMemoryRateLimiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/track", tags=["tracking"])

_rate_limiter = InMemoryRateLimiter(
    max_hits=settings.TRACKING_RATE_LIMIT_PER_MINUTE,
    window_seconds=60,
)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(request: Request, bucket: str) -> dict[str, Any] | None:
    key = f"{bucket}:{_client_ip(request)}"
    if _rate_limiter.hit(key):
        return None
    return {"ok": False, "error": "rate_limited"}


def _safe_error(exc: Exception, context: str) -> dict[str, Any]:
    logger.exception("tracking endpoint failure: %s", context)
    return {"ok": False, "error": "internal_error"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class _TrackBase(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    workspace_token: str = Field(..., min_length=1, max_length=128)


class SessionTrackBody(_TrackBase):
    url: str | None = None
    referrer: str | None = None
    user_agent: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    gclid: str | None = None
    fbclid: str | None = None


class PageviewBody(_TrackBase):
    url: str
    referrer: str | None = None
    title: str | None = None
    time_on_page_seconds: int | None = None


class IdentifyBody(_TrackBase):
    email: str
    first_name: str | None = None
    last_name: str | None = None


class FormBody(_TrackBase):
    form_id: str
    form_data: dict[str, Any]
    page_url: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/session")
async def track_session(
    body: SessionTrackBody,
    request: Request,
    db: DbSession,
) -> dict[str, Any]:
    if (rl := _rate_limited(request, "session")) is not None:
        return rl
    try:
        workspace = await resolve_workspace_by_token(db, body.workspace_token)
        if workspace is None:
            return {"ok": False, "error": "invalid_token"}

        session, is_new = await upsert_session(
            db,
            workspace_id=workspace.id,
            session_id=body.session_id,
            url=body.url,
            referrer=body.referrer,
            user_agent=body.user_agent,
            ip_address=_client_ip(request),
            utm_source=body.utm_source,
            utm_medium=body.utm_medium,
            utm_campaign=body.utm_campaign,
            utm_content=body.utm_content,
            utm_term=body.utm_term,
            gclid=body.gclid,
            fbclid=body.fbclid,
        )
        await db.commit()
        return {"ok": True, "session_id": str(session.id), "is_new": is_new}
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        return _safe_error(exc, "track/session")


@router.post("/pageview")
async def track_pageview(
    body: PageviewBody,
    request: Request,
    db: DbSession,
) -> dict[str, Any]:
    if (rl := _rate_limited(request, "pageview")) is not None:
        return rl
    try:
        workspace = await resolve_workspace_by_token(db, body.workspace_token)
        if workspace is None:
            return {"ok": False, "error": "invalid_token"}

        session, _ = await upsert_session(
            db,
            workspace_id=workspace.id,
            session_id=body.session_id,
            url=body.url,
            referrer=body.referrer,
            ip_address=_client_ip(request),
        )

        db.add(
            PageView(
                workspace_id=workspace.id,
                session_id=session.id,
                url=body.url,
                referrer=body.referrer,
                title=body.title,
                time_on_page_seconds=body.time_on_page_seconds,
            )
        )
        await db.commit()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        return _safe_error(exc, "track/pageview")


@router.post("/identify")
async def track_identify(
    body: IdentifyBody,
    request: Request,
    db: DbSession,
) -> dict[str, Any]:
    if (rl := _rate_limited(request, "identify")) is not None:
        return rl
    try:
        workspace = await resolve_workspace_by_token(db, body.workspace_token)
        if workspace is None:
            return {"ok": False, "error": "invalid_token"}

        contact = await process_identify(
            db,
            workspace_id=workspace.id,
            session_id=body.session_id,
            email=body.email.strip().lower(),
            first_name=body.first_name,
            last_name=body.last_name,
        )
        await db.commit()
        return {"ok": True, "contact_id": str(contact.id)}
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        return _safe_error(exc, "track/identify")


@router.post("/form")
async def track_form(
    body: FormBody,
    request: Request,
    db: DbSession,
) -> dict[str, Any]:
    if (rl := _rate_limited(request, "form")) is not None:
        return rl
    try:
        workspace = await resolve_workspace_by_token(db, body.workspace_token)
        if workspace is None:
            return {"ok": False, "error": "invalid_token"}

        result = await process_form_submission(
            db,
            workspace_id=workspace.id,
            session_id=body.session_id,
            form_id=body.form_id,
            form_data=body.form_data,
            page_url=body.page_url,
        )
        await db.commit()
        await enqueue_lead_scorer_post_commit(
            workspace.id, UUID(result["lead_id"])
        )
        return {"ok": True, **result}
    except ValueError as exc:
        await db.rollback()
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        return _safe_error(exc, "track/form")


# A 1x1 transparent GIF — the smallest tracking pixel that exists.
_TRANSPARENT_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


@router.get("/pixel/{workspace_token}")
async def tracking_pixel(
    request: Request,
    db: DbSession,
    workspace_token: Annotated[str, Path(..., min_length=1, max_length=128)],
) -> Response:
    """1x1 GIF pixel for email-open tracking.

    Always returns the GIF — even on invalid token — so attackers cannot
    probe for valid tokens by image-load diffing.
    """
    if _rate_limited(request, "pixel") is not None:
        # Silently drop without recording — still serve the pixel.
        return Response(content=_TRANSPARENT_GIF, media_type="image/gif")

    try:
        workspace = await resolve_workspace_by_token(db, workspace_token)
        if workspace is not None:
            # Future: record an open event keyed by query-string message_id.
            message_id = request.query_params.get("m")
            if message_id:
                logger.info(
                    "pixel open: workspace=%s message=%s",
                    workspace.id,
                    message_id,
                )
    except Exception:  # noqa: BLE001
        logger.exception("tracking pixel handler failed")

    return Response(content=_TRANSPARENT_GIF, media_type="image/gif")
