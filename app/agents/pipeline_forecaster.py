"""Pipeline Forecaster — weekly Claude-powered revenue forecast + at-risk deal flag.

Triggered weekly by the ARQ cron `run_pipeline_forecaster` (Monday 07:00 UTC)
and on-demand via `POST /forecasts/generate`. Writes:
  - one PipelineForecast row per `current_month` / `next_month` period
  - one Activity (`note`, actor=ai_agent) per at-risk deal
  - invalidates the workspace dashboard cache
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.activity import Activity, ActivityType, ActorType
from app.models.agent_run import AgentType
from app.models.deal import CloseReason, Deal
from app.models.pipeline_forecast import ForecastPeriod, PipelineForecast
from app.models.pipeline_stage import PipelineStage
from app.models.user import User
from app.services.reporting_service import invalidate_dashboard_cache

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert sales forecasting analyst. Based on the pipeline data "
    "provided, generate a revenue forecast and identify at-risk deals. Be "
    "specific about which deals are at risk and why. Return JSON only with "
    "this exact shape: {\"forecast_current_month_cents\": int, "
    "\"forecast_next_month_cents\": int, \"confidence\": \"low\"|\"medium\"|\"high\", "
    "\"at_risk_deals\": [{\"deal_id\": str, \"deal_name\": str, "
    "\"risk_reason\": str, \"recommended_action\": str}], "
    "\"recommendations\": [str], "
    "\"pipeline_health\": \"healthy\"|\"on_track\"|\"below_target\"|\"critical\"}"
)


def _days_between(a: datetime | None, b: datetime) -> int | None:
    if a is None:
        return None
    return max((b - a).days, 0)


class PipelineForecasterAgent(BaseAgent):
    agent_type = AgentType.PIPELINE_FORECASTER
    model = "claude-opus-4-6"

    async def _perform(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        workspace_id: UUID,
        entity_id: UUID | None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], int, int]:
        now = datetime.now(UTC)

        stages = (
            await db.execute(
                select(PipelineStage).where(
                    PipelineStage.workspace_id == workspace_id
                )
            )
        ).scalars().all()
        stage_by_id = {s.id: s for s in stages}

        open_deals = (
            await db.execute(
                select(Deal).where(
                    Deal.workspace_id == workspace_id,
                    Deal.is_active.is_(True),
                    Deal.closed_at.is_(None),
                )
            )
        ).scalars().all()

        owner_ids = {d.owner_id for d in open_deals if d.owner_id is not None}
        users = (
            await db.execute(
                select(User).where(User.id.in_(owner_ids))
            )
        ).scalars().all() if owner_ids else []
        name_by_owner = {
            u.id: " ".join(p for p in [u.first_name, u.last_name] if p) or u.email
            for u in users
        }

        last_activity_by_deal: dict[UUID, datetime] = {}
        if open_deals:
            activity_rows = (
                await db.execute(
                    select(Activity.deal_id, Activity.occurred_at)
                    .where(
                        Activity.workspace_id == workspace_id,
                        Activity.deal_id.in_([d.id for d in open_deals]),
                    )
                    .order_by(Activity.occurred_at.desc())
                )
            ).all()
            for deal_id, occurred_at in activity_rows:
                if deal_id not in last_activity_by_deal:
                    last_activity_by_deal[deal_id] = occurred_at

        ninety_days_ago = now - timedelta(days=90)
        closed_recent = (
            await db.execute(
                select(Deal).where(
                    Deal.workspace_id == workspace_id,
                    Deal.closed_at.is_not(None),
                    Deal.closed_at >= ninety_days_ago,
                )
            )
        ).scalars().all()

        rate_buckets: dict[UUID, dict[str, int]] = {}
        for d in closed_recent:
            if d.pipeline_stage_id is None:
                continue
            bucket = rate_buckets.setdefault(
                d.pipeline_stage_id, {"won": 0, "total": 0}
            )
            bucket["total"] += 1
            if d.close_reason == CloseReason.WON:
                bucket["won"] += 1
        historical_close_rate: dict[str, dict[str, Any]] = {}
        for stage_id, bucket in rate_buckets.items():
            stage = stage_by_id.get(stage_id)
            historical_close_rate[str(stage_id)] = {
                "stage_name": stage.name if stage else None,
                "close_rate": (
                    round(bucket["won"] / bucket["total"], 4)
                    if bucket["total"] else 0.0
                ),
                "sample_size": bucket["total"],
            }

        rep_win_buckets: dict[UUID, dict[str, int]] = {}
        for d in closed_recent:
            if d.owner_id is None:
                continue
            bucket = rep_win_buckets.setdefault(
                d.owner_id, {"won": 0, "total": 0}
            )
            bucket["total"] += 1
            if d.close_reason == CloseReason.WON:
                bucket["won"] += 1
        rep_win_rates = [
            {
                "owner_id": str(oid),
                "name": name_by_owner.get(oid, "Unknown"),
                "win_rate": round(b["won"] / b["total"], 4) if b["total"] else 0.0,
                "sample_size": b["total"],
            }
            for oid, b in rep_win_buckets.items()
        ]

        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
        current_month_won = sum(
            int(d.value_cents or 0)
            for d in closed_recent
            if d.close_reason == CloseReason.WON
            and d.closed_at is not None
            and d.closed_at >= month_start
        )

        previous_forecast = (
            await db.execute(
                select(PipelineForecast)
                .where(
                    PipelineForecast.workspace_id == workspace_id,
                    PipelineForecast.forecast_period == ForecastPeriod.CURRENT_MONTH,
                )
                .order_by(PipelineForecast.forecast_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        deal_context = []
        for d in open_deals:
            stage = stage_by_id.get(d.pipeline_stage_id) if d.pipeline_stage_id else None
            deal_context.append(
                {
                    "deal_id": str(d.id),
                    "name": d.name,
                    "value_cents": int(d.value_cents or 0),
                    "stage": {
                        "name": stage.name if stage else None,
                        "probability": stage.probability_default if stage else d.probability,
                        "is_won": stage.is_won if stage else False,
                        "is_lost": stage.is_lost if stage else False,
                    },
                    "expected_close_date": (
                        d.expected_close_date.isoformat()
                        if d.expected_close_date else None
                    ),
                    "owner_name": (
                        name_by_owner.get(d.owner_id) if d.owner_id else None
                    ),
                    "days_in_stage": _days_between(d.updated_at, now),
                    "days_since_last_activity": _days_between(
                        last_activity_by_deal.get(d.id), now
                    ),
                }
            )

        context = {
            "today": now.date().isoformat(),
            "open_deals": deal_context,
            "historical_close_rate_by_stage": historical_close_rate,
            "rep_win_rates_90d": rep_win_rates,
            "current_month_closed_revenue_cents": current_month_won,
            "previous_forecast": (
                {
                    "forecast_value_cents": previous_forecast.forecast_value_cents,
                    "pipeline_value_cents": previous_forecast.pipeline_value_cents,
                    "forecast_date": previous_forecast.forecast_date.isoformat(),
                }
                if previous_forecast is not None else None
            ),
        }

        total_pipeline = sum(int(d.value_cents or 0) for d in open_deals)
        weighted = sum(
            int(d.value_cents or 0) * int(d.probability or 0) // 100
            for d in open_deals
        )

        mock = {
            "forecast_current_month_cents": current_month_won + weighted // 2,
            "forecast_next_month_cents": weighted,
            "confidence": "medium",
            "at_risk_deals": [],
            "recommendations": ["Mock forecast — ANTHROPIC_API_KEY not configured."],
            "pipeline_health": "on_track",
        }
        parsed, in_tok, out_tok = await self._call_claude(
            system=SYSTEM_PROMPT,
            user=json.dumps(context, default=str),
            max_tokens=2048,
            mock_output=mock,
        )

        try:
            forecast_current = int(parsed.get("forecast_current_month_cents", 0))
        except (TypeError, ValueError):
            forecast_current = 0
        try:
            forecast_next = int(parsed.get("forecast_next_month_cents", 0))
        except (TypeError, ValueError):
            forecast_next = 0

        at_risk_raw = parsed.get("at_risk_deals") or []
        at_risk_ids: list[str] = []
        valid_deal_ids = {str(d.id) for d in open_deals}
        for entry in at_risk_raw:
            if not isinstance(entry, dict):
                continue
            deal_id_str = str(entry.get("deal_id", ""))
            if deal_id_str not in valid_deal_ids:
                continue
            at_risk_ids.append(deal_id_str)
            try:
                deal_uuid = UUID(deal_id_str)
            except ValueError:
                continue
            risk_reason = str(entry.get("risk_reason", ""))
            recommended = str(entry.get("recommended_action", ""))
            body = f"{risk_reason}\n\nRecommended: {recommended}".strip()
            db.add(
                Activity(
                    workspace_id=workspace_id,
                    deal_id=deal_uuid,
                    actor_type=ActorType.AI_AGENT,
                    type=ActivityType.NOTE,
                    subject=f"At-risk: {entry.get('deal_name', 'deal')}",
                    body=body,
                    meta={
                        "agent_run_id": str(run_id),
                        "risk_reason": risk_reason,
                        "recommended_action": recommended,
                    },
                )
            )

        recommendations = parsed.get("recommendations") or []
        if not isinstance(recommendations, list):
            recommendations = []

        today = date.today()
        for period, value in (
            (ForecastPeriod.CURRENT_MONTH, forecast_current),
            (ForecastPeriod.NEXT_MONTH, forecast_next),
        ):
            db.add(
                PipelineForecast(
                    workspace_id=workspace_id,
                    forecast_period=period,
                    forecast_date=today,
                    forecast_value_cents=value,
                    pipeline_value_cents=total_pipeline,
                    deal_count=len(open_deals),
                    at_risk_deal_ids=at_risk_ids,
                    agent_run_id=run_id,
                    recommendations=recommendations,
                )
            )

        # Summary entry on the workspace activity log — uses no contact/deal
        # link so it shows up as a workspace-wide audit event.
        summary_subject = (
            f"Pipeline forecast generated — current month "
            f"${forecast_current // 100:,}, next month ${forecast_next // 100:,}"
        )
        db.add(
            Activity(
                workspace_id=workspace_id,
                actor_type=ActorType.AI_AGENT,
                type=ActivityType.NOTE,
                subject=summary_subject,
                body="\n".join(str(r) for r in recommendations) or None,
                meta={
                    "agent_run_id": str(run_id),
                    "forecast_current_month_cents": forecast_current,
                    "forecast_next_month_cents": forecast_next,
                    "at_risk_deal_count": len(at_risk_ids),
                    "pipeline_health": parsed.get("pipeline_health"),
                },
            )
        )

        await invalidate_dashboard_cache(db, workspace_id)

        return parsed, in_tok, out_tok
