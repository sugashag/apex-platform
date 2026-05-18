"""Attribution services — first-touch resolution, deal backfill, reporting."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attribution import Attribution, TouchType
from app.models.deal import CloseReason, Deal
from app.models.lead import Lead
from app.models.page_view import PageView
from app.models.visitor_session import VisitorSession


async def resolve_first_touch(
    db: AsyncSession,
    workspace_id: UUID,
    contact_id: UUID,
) -> Attribution | None:
    """Return the existing first_touch Attribution for a contact, if any."""
    result = await db.execute(
        select(Attribution)
        .where(
            Attribution.workspace_id == workspace_id,
            Attribution.contact_id == contact_id,
            Attribution.touch_type == TouchType.FIRST_TOUCH,
        )
        .order_by(Attribution.occurred_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_attribution_from_session(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    contact_id: UUID,
    session: VisitorSession | None,
    touch_type: TouchType,
    occurred_at: datetime | None = None,
) -> Attribution:
    """Create an Attribution row from a VisitorSession's captured UTM data.

    `session` may be None — in that case the Attribution is created with no
    source data (still useful for funnel counting of unattributed contacts).
    Caller commits the transaction.
    """
    attribution = Attribution(
        workspace_id=workspace_id,
        contact_id=contact_id,
        session_id=session.id if session is not None else None,
        touch_type=touch_type,
        source=session.source if session else None,
        campaign=session.campaign if session else None,
        medium=session.medium if session else None,
        content=session.content if session else None,
        term=session.term if session else None,
        landing_page_url=session.landing_page_url if session else None,
        referrer_url=session.referrer_url if session else None,
        gclid=session.gclid if session else None,
        fbclid=session.fbclid if session else None,
        occurred_at=(
            occurred_at
            if occurred_at is not None
            else (session.first_seen_at if session else datetime.now(UTC))
        ),
    )
    db.add(attribution)
    await db.flush()
    return attribution


async def link_deal_to_attributions(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    contact_id: UUID,
    deal_id: UUID,
) -> int:
    """Backfill `deal_id` on every Attribution row for the contact.

    Returns the number of rows updated. Caller commits.
    """
    result = await db.execute(
        update(Attribution)
        .where(
            Attribution.workspace_id == workspace_id,
            Attribution.contact_id == contact_id,
            Attribution.deal_id.is_(None),
        )
        .values(deal_id=deal_id)
    )
    return int(result.rowcount or 0)


# --- reporting --------------------------------------------------------------


def _attribution_value(value: str | None) -> str:
    return value or "unknown"


async def _attributions_in_range(
    db: AsyncSession,
    workspace_id: UUID,
    start_date: datetime | None,
    end_date: datetime | None,
) -> list[Attribution]:
    stmt = select(Attribution).where(
        Attribution.workspace_id == workspace_id,
        Attribution.touch_type == TouchType.FIRST_TOUCH,
    )
    if start_date is not None:
        stmt = stmt.where(Attribution.occurred_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(Attribution.occurred_at <= end_date)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _deals_for_contacts(
    db: AsyncSession,
    workspace_id: UUID,
    contact_ids: Iterable[UUID],
) -> dict[UUID, list[Deal]]:
    ids = list(set(contact_ids))
    if not ids:
        return {}
    result = await db.execute(
        select(Deal).where(
            Deal.workspace_id == workspace_id,
            Deal.contact_id.in_(ids),
            Deal.is_active.is_(True),
        )
    )
    grouped: dict[UUID, list[Deal]] = {}
    for deal in result.scalars().all():
        if deal.contact_id is None:
            continue
        grouped.setdefault(deal.contact_id, []).append(deal)
    return grouped


def _aggregate_by_key(
    attributions: list[Attribution],
    deals_by_contact: dict[UUID, list[Deal]],
    key_fn: Callable[[Attribution], str | None],
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}

    for attr in attributions:
        key = _attribution_value(key_fn(attr))
        b = buckets.setdefault(
            key,
            {
                "lead_count": 0,
                "deal_count": 0,
                "won_deal_count": 0,
                "pipeline_value_cents": 0,
                "won_value_cents": 0,
                "_close_days": [],
                "_contact_ids": set(),
            },
        )
        b["_contact_ids"].add(attr.contact_id)
        b["lead_count"] += 1

        for deal in deals_by_contact.get(attr.contact_id, []):
            b["deal_count"] += 1
            value = int(deal.value_cents or 0)
            b["pipeline_value_cents"] += value
            if deal.close_reason == CloseReason.WON:
                b["won_deal_count"] += 1
                b["won_value_cents"] += value
                if deal.closed_at is not None:
                    delta = deal.closed_at - attr.occurred_at
                    b["_close_days"].append(max(delta.days, 0))

    rows: list[dict[str, Any]] = []
    for key, b in buckets.items():
        close_days = b.pop("_close_days")
        b.pop("_contact_ids")
        rows.append(
            {
                "key": key,
                "lead_count": b["lead_count"],
                "deal_count": b["deal_count"],
                "won_deal_count": b["won_deal_count"],
                "pipeline_value_cents": b["pipeline_value_cents"],
                "won_value_cents": b["won_value_cents"],
                "avg_days_to_close": (
                    round(sum(close_days) / len(close_days), 1)
                    if close_days
                    else None
                ),
            }
        )
    rows.sort(key=lambda r: r["won_value_cents"], reverse=True)
    return rows


async def get_source_report(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[dict[str, Any]]:
    """Aggregate first-touch attributions + deal outcomes by `source`."""
    attributions = await _attributions_in_range(
        db, workspace_id, start_date, end_date
    )
    deals_by_contact = await _deals_for_contacts(
        db, workspace_id, [a.contact_id for a in attributions]
    )
    rows = _aggregate_by_key(attributions, deals_by_contact, lambda a: a.source)
    return [{"source": r.pop("key"), **r} for r in rows]


async def get_campaign_report(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[dict[str, Any]]:
    """Aggregate first-touch attributions + deal outcomes by `campaign`."""
    attributions = await _attributions_in_range(
        db, workspace_id, start_date, end_date
    )
    deals_by_contact = await _deals_for_contacts(
        db, workspace_id, [a.contact_id for a in attributions]
    )
    rows = _aggregate_by_key(attributions, deals_by_contact, lambda a: a.campaign)
    return [{"campaign": r.pop("key"), **r} for r in rows]


async def get_funnel_report(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> dict[str, Any]:
    """Visitor → session → lead → deal → won funnel for the date range."""

    def _range(col: Any) -> Any:
        clauses = []
        if start_date is not None:
            clauses.append(col >= start_date)
        if end_date is not None:
            clauses.append(col <= end_date)
        return clauses

    page_view_filters = _range(PageView.occurred_at)
    pv_count_result = await db.execute(
        select(func.count()).select_from(
            select(PageView)
            .where(PageView.workspace_id == workspace_id, *page_view_filters)
            .subquery()
        )
    )
    pageviews = int(pv_count_result.scalar_one())

    session_filters = _range(VisitorSession.first_seen_at)
    sessions_result = await db.execute(
        select(func.count()).select_from(
            select(VisitorSession)
            .where(VisitorSession.workspace_id == workspace_id, *session_filters)
            .subquery()
        )
    )
    sessions = int(sessions_result.scalar_one())

    lead_filters = _range(Lead.created_at)
    leads_result = await db.execute(
        select(func.count()).select_from(
            select(Lead)
            .where(Lead.workspace_id == workspace_id, *lead_filters)
            .subquery()
        )
    )
    leads = int(leads_result.scalar_one())

    deal_filters = _range(Deal.created_at)
    deals_result = await db.execute(
        select(func.count()).select_from(
            select(Deal)
            .where(
                Deal.workspace_id == workspace_id,
                Deal.is_active.is_(True),
                *deal_filters,
            )
            .subquery()
        )
    )
    deals = int(deals_result.scalar_one())

    won_result = await db.execute(
        select(func.count()).select_from(
            select(Deal)
            .where(
                Deal.workspace_id == workspace_id,
                Deal.is_active.is_(True),
                Deal.close_reason == CloseReason.WON,
                *_range(Deal.closed_at),
            )
            .subquery()
        )
    )
    won = int(won_result.scalar_one())

    def _rate(numerator: int, denominator: int) -> float | None:
        if denominator == 0:
            return None
        return round(numerator / denominator, 4)

    return {
        "pageviews": pageviews,
        "sessions": sessions,
        "leads": leads,
        "deals": deals,
        "won": won,
        "conversion_rates": {
            "pageview_to_session": _rate(sessions, pageviews),
            "session_to_lead": _rate(leads, sessions),
            "lead_to_deal": _rate(deals, leads),
            "deal_to_won": _rate(won, deals),
        },
    }


async def get_cac_report(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    ad_spend_cents: int,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[dict[str, Any]]:
    """CAC per source: simple ad_spend / won_deal_count for the period.

    `ad_spend_cents` is the *total* spend; we distribute it evenly across
    sources whose attribution share matches the won-deal volume. Sources
    with zero won deals get `cac_cents = None`.
    """
    source_rows = await get_source_report(
        db,
        workspace_id=workspace_id,
        start_date=start_date,
        end_date=end_date,
    )
    total_won = sum(r["won_deal_count"] for r in source_rows)
    rows: list[dict[str, Any]] = []
    for r in source_rows:
        won_count = r["won_deal_count"]
        if total_won == 0 or won_count == 0:
            cac_cents: int | None = None
        else:
            share = won_count / total_won
            allocated = int(ad_spend_cents * share)
            cac_cents = allocated // won_count if won_count else None
        rows.append(
            {
                "source": r["source"],
                "won_deal_count": won_count,
                "won_value_cents": r["won_value_cents"],
                "allocated_spend_cents": (
                    int(ad_spend_cents * (won_count / total_won))
                    if total_won
                    else 0
                ),
                "cac_cents": cac_cents,
            }
        )
    return rows


async def get_contact_chain(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    contact_id: UUID,
) -> list[Attribution]:
    """All Attribution rows for a contact in chronological order."""
    result = await db.execute(
        select(Attribution)
        .where(
            Attribution.workspace_id == workspace_id,
            Attribution.contact_id == contact_id,
        )
        .order_by(Attribution.occurred_at.asc())
    )
    return list(result.scalars().all())


async def get_deal_chain(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    deal_id: UUID,
) -> list[Attribution]:
    """All Attribution rows linked to a deal, chronological."""
    result = await db.execute(
        select(Attribution)
        .where(
            Attribution.workspace_id == workspace_id,
            Attribution.deal_id == deal_id,
        )
        .order_by(Attribution.occurred_at.asc())
    )
    return list(result.scalars().all())


__all__ = [
    "create_attribution_from_session",
    "get_cac_report",
    "get_campaign_report",
    "get_contact_chain",
    "get_deal_chain",
    "get_funnel_report",
    "get_source_report",
    "link_deal_to_attributions",
    "resolve_first_touch",
]
