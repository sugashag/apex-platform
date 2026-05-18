"""Reporting service — pipeline, revenue, lead, rep, and dashboard aggregations.

These functions return plain dicts/lists for direct JSON serialization. They
are intentionally chatty (multiple round-trips) for clarity; the dashboard
endpoint wraps them through ``compute_and_cache_metrics`` so the hot path
serves cached results.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity, ActivityType
from app.models.call import Call
from app.models.dashboard_metric_cache import DashboardMetricCache
from app.models.deal import CloseReason, Deal
from app.models.lead import Lead, LeadStatus
from app.models.lead_score_history import LeadScoreHistory
from app.models.message import Message, MessageDirection
from app.models.pipeline_stage import PipelineStage
from app.models.user import User

CACHE_TTL_SECONDS = 3600  # 1 hour, matches the refresh cron cadence.


# --- helpers ---------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _start_of_period(period: str, now: datetime | None = None) -> datetime:
    n = now or _utcnow()
    if period == "month":
        return datetime(n.year, n.month, 1, tzinfo=UTC)
    if period == "week":
        return datetime(n.year, n.month, n.day, tzinfo=UTC) - timedelta(days=n.weekday())
    if period == "today":
        return datetime(n.year, n.month, n.day, tzinfo=UTC)
    raise ValueError(f"unknown period: {period}")


# --- pipeline --------------------------------------------------------------


async def get_pipeline_summary(
    db: AsyncSession,
    workspace_id: UUID,
    owner_id: UUID | None = None,
) -> dict[str, Any]:
    """Open-deal counts and values, broken down by pipeline stage."""
    stages = (
        await db.execute(
            select(PipelineStage)
            .where(PipelineStage.workspace_id == workspace_id)
            .order_by(PipelineStage.position.asc())
        )
    ).scalars().all()

    deal_stmt = select(Deal).where(
        Deal.workspace_id == workspace_id,
        Deal.is_active.is_(True),
        Deal.closed_at.is_(None),
    )
    if owner_id is not None:
        deal_stmt = deal_stmt.where(Deal.owner_id == owner_id)
    deals = (await db.execute(deal_stmt)).scalars().all()

    by_stage_id: dict[UUID, dict[str, Any]] = {}
    for stage in stages:
        by_stage_id[stage.id] = {
            "stage_id": str(stage.id),
            "stage_name": stage.name,
            "position": stage.position,
            "deal_count": 0,
            "value_cents": 0,
            "probability": stage.probability_default,
        }

    total_value = 0
    weighted = 0
    for d in deals:
        value = int(d.value_cents or 0)
        total_value += value
        weighted += value * int(d.probability or 0) // 100
        if d.pipeline_stage_id is not None and d.pipeline_stage_id in by_stage_id:
            bucket = by_stage_id[d.pipeline_stage_id]
            bucket["deal_count"] += 1
            bucket["value_cents"] += value

    return {
        "total_pipeline_value_cents": total_value,
        "deal_count": len(deals),
        "by_stage": list(by_stage_id.values()),
        "weighted_pipeline_cents": weighted,
    }


async def get_pipeline_velocity(
    db: AsyncSession,
    workspace_id: UUID,
    days: int = 90,
) -> dict[str, Any]:
    """Average days a deal spends in each stage, computed from stage_change activities."""
    since = _utcnow() - timedelta(days=days)

    stages = (
        await db.execute(
            select(PipelineStage)
            .where(PipelineStage.workspace_id == workspace_id)
            .order_by(PipelineStage.position.asc())
        )
    ).scalars().all()
    stage_name_by_id: dict[str, str] = {str(s.id): s.name for s in stages}

    rows = (
        await db.execute(
            select(Activity)
            .where(
                Activity.workspace_id == workspace_id,
                Activity.type == ActivityType.STAGE_CHANGE,
                Activity.occurred_at >= since,
            )
            .order_by(Activity.deal_id.asc(), Activity.occurred_at.asc())
        )
    ).scalars().all()

    durations: dict[str, list[float]] = defaultdict(list)
    grouped: dict[UUID, list[Activity]] = defaultdict(list)
    for a in rows:
        if a.deal_id is not None:
            grouped[a.deal_id].append(a)

    for activities in grouped.values():
        for prev, nxt in zip(activities, activities[1:], strict=False):
            meta = prev.meta or {}
            stage_id = meta.get("to_stage_id")
            if stage_id is None:
                continue
            delta = nxt.occurred_at - prev.occurred_at
            durations[str(stage_id)].append(max(delta.total_seconds() / 86400, 0))

    return {
        "by_stage": [
            {
                "stage_id": sid,
                "stage_name": stage_name_by_id.get(sid, "unknown"),
                "avg_days_in_stage": (
                    round(sum(samples) / len(samples), 2) if samples else None
                ),
                "sample_size": len(samples),
            }
            for sid, samples in durations.items()
        ],
        "window_days": days,
    }


# --- win rate / revenue ----------------------------------------------------


async def get_win_rate(
    db: AsyncSession,
    workspace_id: UUID,
    days: int = 90,
    owner_id: UUID | None = None,
) -> dict[str, Any]:
    """Win rate, avg deal size, avg days to close for closed deals in window."""
    since = _utcnow() - timedelta(days=days)
    stmt = select(Deal).where(
        Deal.workspace_id == workspace_id,
        Deal.closed_at.is_not(None),
        Deal.closed_at >= since,
    )
    if owner_id is not None:
        stmt = stmt.where(Deal.owner_id == owner_id)
    deals = (await db.execute(stmt)).scalars().all()

    won = [d for d in deals if d.close_reason == CloseReason.WON]
    lost = [d for d in deals if d.close_reason == CloseReason.LOST]
    closed = won + lost

    win_rate = (len(won) / len(closed)) if closed else 0.0
    avg_size = (
        int(sum(d.value_cents or 0 for d in won) / len(won)) if won else 0
    )
    days_to_close: list[float] = []
    for d in won:
        if d.closed_at is None:
            continue
        delta = d.closed_at - d.created_at
        days_to_close.append(max(delta.total_seconds() / 86400, 0))
    avg_days = round(sum(days_to_close) / len(days_to_close), 1) if days_to_close else None

    return {
        "window_days": days,
        "won_count": len(won),
        "lost_count": len(lost),
        "win_rate": round(win_rate, 4),
        "avg_deal_size_cents": avg_size,
        "avg_days_to_close": avg_days,
        "won_value_cents": sum(d.value_cents or 0 for d in won),
    }


async def get_revenue_by_month(
    db: AsyncSession,
    workspace_id: UUID,
    months: int = 12,
) -> list[dict[str, Any]]:
    """Won revenue grouped by year-month for the trailing N months."""
    since = _utcnow() - timedelta(days=months * 31)
    rows = (
        await db.execute(
            select(Deal).where(
                Deal.workspace_id == workspace_id,
                Deal.close_reason == CloseReason.WON,
                Deal.closed_at.is_not(None),
                Deal.closed_at >= since,
            )
        )
    ).scalars().all()

    buckets: dict[str, dict[str, Any]] = {}
    for d in rows:
        if d.closed_at is None:
            continue
        key = d.closed_at.strftime("%Y-%m")
        bucket = buckets.setdefault(
            key, {"month": key, "won_deal_count": 0, "won_value_cents": 0}
        )
        bucket["won_deal_count"] += 1
        bucket["won_value_cents"] += int(d.value_cents or 0)

    return sorted(buckets.values(), key=lambda b: b["month"])


async def get_revenue_by_rep(
    db: AsyncSession,
    workspace_id: UUID,
    days: int = 90,
) -> list[dict[str, Any]]:
    """Won revenue per owner over the window."""
    since = _utcnow() - timedelta(days=days)
    rows = (
        await db.execute(
            select(Deal).where(
                Deal.workspace_id == workspace_id,
                Deal.close_reason == CloseReason.WON,
                Deal.closed_at.is_not(None),
                Deal.closed_at >= since,
            )
        )
    ).scalars().all()

    by_owner: dict[UUID | None, dict[str, Any]] = {}
    for d in rows:
        bucket = by_owner.setdefault(
            d.owner_id,
            {
                "owner_id": str(d.owner_id) if d.owner_id else None,
                "won_deal_count": 0,
                "won_value_cents": 0,
            },
        )
        bucket["won_deal_count"] += 1
        bucket["won_value_cents"] += int(d.value_cents or 0)

    owner_ids = [oid for oid in by_owner if oid is not None]
    name_by_id: dict[UUID, str] = {}
    if owner_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(owner_ids)))
        ).scalars().all()
        for u in users:
            name_parts = [p for p in [u.first_name, u.last_name] if p]
            name_by_id[u.id] = " ".join(name_parts) or u.email

    result: list[dict[str, Any]] = []
    for oid, bucket in by_owner.items():
        bucket["name"] = name_by_id.get(oid) if oid else "Unassigned"
        result.append(bucket)
    result.sort(key=lambda r: int(r["won_value_cents"]), reverse=True)
    return result


# --- rep performance -------------------------------------------------------


async def get_rep_performance(
    db: AsyncSession,
    workspace_id: UUID,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Per-rep activity + outcomes summary for the window."""
    since = _utcnow() - timedelta(days=days)

    users = (
        await db.execute(
            select(User).where(
                User.workspace_id == workspace_id,
                User.is_active.is_(True),
            )
        )
    ).scalars().all()

    calls_rows = (
        await db.execute(
            select(Call.initiated_by_id, func.count(Call.id))
            .where(
                Call.workspace_id == workspace_id,
                Call.started_at.is_not(None),
                Call.started_at >= since,
            )
            .group_by(Call.initiated_by_id)
        )
    ).all()
    calls_by_user: dict[UUID | None, int] = {r[0]: int(r[1]) for r in calls_rows}

    # Emails sent: approximate as messages whose direction is outbound and
    # whose actor is the rep (look it up via Activity rows since the Message
    # itself doesn't carry actor_id).
    activity_rows = (
        await db.execute(
            select(Activity.actor_id, Activity.type, func.count(Activity.id))
            .where(
                Activity.workspace_id == workspace_id,
                Activity.occurred_at >= since,
                Activity.actor_id.is_not(None),
            )
            .group_by(Activity.actor_id, Activity.type)
        )
    ).all()
    emails_by_user: dict[UUID, int] = defaultdict(int)
    for actor_id, atype, count in activity_rows:
        if atype == ActivityType.EMAIL_SENT:
            emails_by_user[actor_id] += int(count)

    deals_created_rows = (
        await db.execute(
            select(Deal.owner_id, func.count(Deal.id))
            .where(
                Deal.workspace_id == workspace_id,
                Deal.created_at >= since,
            )
            .group_by(Deal.owner_id)
        )
    ).all()
    deals_created_by_user: dict[UUID | None, int] = {
        r[0]: int(r[1]) for r in deals_created_rows
    }

    won_rows = (
        await db.execute(
            select(
                Deal.owner_id,
                func.count(Deal.id),
                func.coalesce(func.sum(Deal.value_cents), 0),
            )
            .where(
                Deal.workspace_id == workspace_id,
                Deal.close_reason == CloseReason.WON,
                Deal.closed_at.is_not(None),
                Deal.closed_at >= since,
            )
            .group_by(Deal.owner_id)
        )
    ).all()
    won_by_user: dict[UUID | None, tuple[int, int]] = {
        r[0]: (int(r[1]), int(r[2])) for r in won_rows
    }

    avg_score_rows = (
        await db.execute(
            select(Lead.owner_id, func.coalesce(func.avg(Lead.score), 0.0))
            .where(Lead.workspace_id == workspace_id)
            .group_by(Lead.owner_id)
        )
    ).all()
    avg_score_by_user: dict[UUID | None, float] = {
        r[0]: float(r[1]) for r in avg_score_rows
    }

    result: list[dict[str, Any]] = []
    for u in users:
        won_count, won_value = won_by_user.get(u.id, (0, 0))
        result.append(
            {
                "user_id": str(u.id),
                "name": " ".join(p for p in [u.first_name, u.last_name] if p) or u.email,
                "calls_made": calls_by_user.get(u.id, 0),
                "emails_sent": emails_by_user.get(u.id, 0),
                "deals_created": deals_created_by_user.get(u.id, 0),
                "deals_won": won_count,
                "revenue_won_cents": won_value,
                "avg_lead_score_owned": round(avg_score_by_user.get(u.id, 0.0), 2),
            }
        )
    result.sort(key=lambda r: int(r["revenue_won_cents"]), reverse=True)
    return result


# --- lead velocity ---------------------------------------------------------


async def get_lead_velocity(
    db: AsyncSession,
    workspace_id: UUID,
    days: int = 30,
) -> dict[str, Any]:
    """Lead volume, qualification/conversion rates, and score distribution."""
    since = _utcnow() - timedelta(days=days)
    leads = (
        await db.execute(
            select(Lead).where(
                Lead.workspace_id == workspace_id,
                Lead.created_at >= since,
            )
        )
    ).scalars().all()

    new_leads = len(leads)
    qualified = [
        lead for lead in leads
        if lead.status in (LeadStatus.QUALIFIED, LeadStatus.CONVERTED)
    ]
    converted = [
        lead for lead in leads if lead.status == LeadStatus.CONVERTED
    ]

    # "days to qualify" is approximated from created_at → updated_at when
    # the lead reached a qualified status. For converted leads we use
    # converted_at if present.
    def _days_between(start: datetime, end: datetime) -> float:
        return max((end - start).total_seconds() / 86400, 0)

    qualify_days: list[float] = [
        _days_between(lead.created_at, lead.updated_at) for lead in qualified
    ]
    convert_days: list[float] = [
        _days_between(lead.created_at, lead.converted_at)
        for lead in converted
        if lead.converted_at is not None
    ]

    distribution = {"0-25": 0, "26-50": 0, "51-75": 0, "76-100": 0}
    for lead in leads:
        s = lead.score
        if s <= 25:
            distribution["0-25"] += 1
        elif s <= 50:
            distribution["26-50"] += 1
        elif s <= 75:
            distribution["51-75"] += 1
        else:
            distribution["76-100"] += 1

    return {
        "window_days": days,
        "new_leads": new_leads,
        "qualified_leads": len(qualified),
        "converted_leads": len(converted),
        "qualification_rate": round(len(qualified) / new_leads, 4) if new_leads else 0.0,
        "conversion_rate": round(len(converted) / new_leads, 4) if new_leads else 0.0,
        "avg_days_to_qualify": (
            round(sum(qualify_days) / len(qualify_days), 1) if qualify_days else None
        ),
        "avg_days_to_convert": (
            round(sum(convert_days) / len(convert_days), 1) if convert_days else None
        ),
        "score_distribution": distribution,
    }


async def get_leads_by_source(
    db: AsyncSession,
    workspace_id: UUID,
    days: int = 90,
) -> list[dict[str, Any]]:
    """Lead count + converted count grouped by Lead.source."""
    since = _utcnow() - timedelta(days=days)
    leads = (
        await db.execute(
            select(Lead).where(
                Lead.workspace_id == workspace_id,
                Lead.created_at >= since,
            )
        )
    ).scalars().all()
    buckets: dict[str, dict[str, Any]] = {}
    for lead in leads:
        key = lead.source or "unknown"
        b = buckets.setdefault(
            key, {"source": key, "lead_count": 0, "converted_count": 0}
        )
        b["lead_count"] += 1
        if lead.status == LeadStatus.CONVERTED:
            b["converted_count"] += 1
    rows = list(buckets.values())
    for r in rows:
        r["conversion_rate"] = (
            round(r["converted_count"] / r["lead_count"], 4)
            if r["lead_count"] else 0.0
        )
    rows.sort(key=lambda r: r["lead_count"], reverse=True)
    return rows


# --- activity --------------------------------------------------------------


async def get_activity_summary(
    db: AsyncSession,
    workspace_id: UUID,
    days: int = 7,
    owner_id: UUID | None = None,
) -> dict[str, Any]:
    """Activity counts by type and per-day series."""
    since = _utcnow() - timedelta(days=days)

    stmt = select(Activity).where(
        Activity.workspace_id == workspace_id,
        Activity.occurred_at >= since,
    )
    if owner_id is not None:
        stmt = stmt.where(Activity.actor_id == owner_id)
    rows = (await db.execute(stmt)).scalars().all()

    by_type: dict[str, int] = defaultdict(int)
    by_day: dict[str, dict[str, int]] = defaultdict(
        lambda: {"call": 0, "email_sent": 0, "email_received": 0, "note": 0, "meeting": 0}
    )
    for a in rows:
        type_val = a.type.value
        by_type[type_val] += 1
        day_key = a.occurred_at.strftime("%Y-%m-%d")
        if type_val in by_day[day_key]:
            by_day[day_key][type_val] += 1

    # Also count inbound/outbound messages directly for richer "emails this week".
    msg_rows = (
        await db.execute(
            select(Message.direction, func.count(Message.id))
            .where(
                Message.workspace_id == workspace_id,
                Message.sent_at >= since,
            )
            .group_by(Message.direction)
        )
    ).all()
    emails_sent = next(
        (int(c) for d, c in msg_rows if d == MessageDirection.OUTBOUND), 0
    )
    emails_received = next(
        (int(c) for d, c in msg_rows if d == MessageDirection.INBOUND), 0
    )

    return {
        "window_days": days,
        "by_type": dict(by_type),
        "by_day": [
            {"date": day, **counts}
            for day, counts in sorted(by_day.items())
        ],
        "emails_sent": emails_sent,
        "emails_received": emails_received,
    }


# --- score trend -----------------------------------------------------------


async def get_lead_score_trend(
    db: AsyncSession,
    workspace_id: UUID,
    lead_id: UUID,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Time-series of LeadScoreHistory rows for a lead."""
    since = _utcnow() - timedelta(days=days)
    rows = (
        await db.execute(
            select(LeadScoreHistory)
            .where(
                LeadScoreHistory.workspace_id == workspace_id,
                LeadScoreHistory.lead_id == lead_id,
                LeadScoreHistory.created_at >= since,
            )
            .order_by(LeadScoreHistory.created_at.asc())
        )
    ).scalars().all()
    return [
        {
            "scored_at": r.created_at.isoformat(),
            "score": r.score,
            "rationale": r.score_rationale,
            "agent_run_id": str(r.agent_run_id) if r.agent_run_id else None,
        }
        for r in rows
    ]


# --- dashboard cache -------------------------------------------------------


async def compute_and_cache_metrics(
    db: AsyncSession,
    workspace_id: UUID,
) -> dict[str, Any]:
    """Compute the standard dashboard payload and upsert into the cache table.

    Returns the freshly computed payload. Caller commits.
    """
    pipeline = await get_pipeline_summary(db, workspace_id)
    win_rate_90 = await get_win_rate(db, workspace_id, days=90)
    lead_velocity = await get_lead_velocity(db, workspace_id, days=30)
    activity_week = await get_activity_summary(db, workspace_id, days=7)

    month_start = _start_of_period("month")
    leads_this_month = int(
        (
            await db.execute(
                select(func.count(Lead.id)).where(
                    Lead.workspace_id == workspace_id,
                    Lead.created_at >= month_start,
                )
            )
        ).scalar_one()
    )

    calls_this_week = activity_week["by_type"].get("call", 0)
    emails_this_week = activity_week["emails_sent"]

    top_leads_rows = (
        await db.execute(
            select(Lead)
            .where(
                Lead.workspace_id == workspace_id,
                Lead.status.in_([LeadStatus.NEW, LeadStatus.WORKING, LeadStatus.QUALIFIED]),
            )
            .order_by(Lead.score.desc())
            .limit(5)
        )
    ).scalars().all()
    top_leads = [
        {
            "lead_id": str(lead.id),
            "contact_id": str(lead.contact_id),
            "score": lead.score,
            "status": lead.status.value,
        }
        for lead in top_leads_rows
    ]

    # At-risk deals — pulled from the most recent forecast, if any. Doing the
    # import here avoids a circular import with the agent module.
    from app.models.pipeline_forecast import PipelineForecast

    latest_forecast = (
        await db.execute(
            select(PipelineForecast)
            .where(PipelineForecast.workspace_id == workspace_id)
            .order_by(PipelineForecast.forecast_date.desc(), PipelineForecast.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    at_risk_deals = (
        list(latest_forecast.at_risk_deal_ids or [])
        if latest_forecast is not None
        else []
    )

    now = _utcnow()
    payload: dict[str, Any] = {
        "pipeline_value_cents": pipeline["total_pipeline_value_cents"],
        "weighted_pipeline_cents": pipeline["weighted_pipeline_cents"],
        "open_deals": pipeline["deal_count"],
        "leads_this_month": leads_this_month,
        "win_rate_90d": win_rate_90["win_rate"],
        "avg_deal_size_cents": win_rate_90["avg_deal_size_cents"],
        "calls_this_week": calls_this_week,
        "emails_sent_this_week": emails_this_week,
        "at_risk_deals": at_risk_deals,
        "top_leads_by_score": top_leads,
        "lead_score_distribution": lead_velocity["score_distribution"],
        "cached_at": now.isoformat(),
    }

    valid_until = now + timedelta(seconds=CACHE_TTL_SECONDS)
    insert_stmt = pg_insert(DashboardMetricCache).values(
        workspace_id=workspace_id,
        metric_key="dashboard",
        metric_value=payload,
        computed_at=now,
        valid_until=valid_until,
    )
    upsert_stmt = insert_stmt.on_conflict_do_update(
        constraint="uq_dashboard_metric_cache_workspace_key",
        set_={
            "metric_value": insert_stmt.excluded.metric_value,
            "computed_at": insert_stmt.excluded.computed_at,
            "valid_until": insert_stmt.excluded.valid_until,
        },
    )
    await db.execute(upsert_stmt)
    return payload


async def get_cached_dashboard(
    db: AsyncSession,
    workspace_id: UUID,
) -> dict[str, Any]:
    """Return a fresh cached payload; recompute if expired or missing."""
    row = (
        await db.execute(
            select(DashboardMetricCache).where(
                DashboardMetricCache.workspace_id == workspace_id,
                DashboardMetricCache.metric_key == "dashboard",
            )
        )
    ).scalar_one_or_none()
    if row is not None and row.valid_until > _utcnow():
        return dict(row.metric_value)
    payload = await compute_and_cache_metrics(db, workspace_id)
    await db.commit()
    return payload


async def invalidate_dashboard_cache(
    db: AsyncSession,
    workspace_id: UUID,
) -> None:
    """Mark the dashboard cache as expired so the next read recomputes."""
    row = (
        await db.execute(
            select(DashboardMetricCache).where(
                DashboardMetricCache.workspace_id == workspace_id,
                DashboardMetricCache.metric_key == "dashboard",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return
    row.valid_until = _utcnow() - timedelta(seconds=1)


__all__ = [
    "CACHE_TTL_SECONDS",
    "compute_and_cache_metrics",
    "get_activity_summary",
    "get_cached_dashboard",
    "get_lead_score_trend",
    "get_lead_velocity",
    "get_leads_by_source",
    "get_pipeline_summary",
    "get_pipeline_velocity",
    "get_rep_performance",
    "get_revenue_by_month",
    "get_revenue_by_rep",
    "get_win_rate",
    "invalidate_dashboard_cache",
]
