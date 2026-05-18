"""Reporting endpoints — pipeline, revenue, leads, reps, activity, dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.dependencies import CurrentUser, DbSession
from app.middleware.rbac import require_manager_or_above
from app.models.lead import Lead
from app.models.pipeline_forecast import ForecastPeriod, PipelineForecast
from app.models.user import User
from app.services import reporting_service
from app.services.attribution_service import get_source_report

router = APIRouter(prefix="/reports", tags=["reports"])


# --- pipeline --------------------------------------------------------------


@router.get("/pipeline")
async def report_pipeline(
    db: DbSession,
    current_user: CurrentUser,
    owner_id: UUID | None = None,
) -> dict[str, Any]:
    return await reporting_service.get_pipeline_summary(
        db, current_user.workspace_id, owner_id=owner_id
    )


@router.get("/pipeline/forecast")
async def report_pipeline_forecast(
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Latest forecast for both `current_month` and `next_month`."""
    out: dict[str, Any] = {}
    for period in (ForecastPeriod.CURRENT_MONTH, ForecastPeriod.NEXT_MONTH):
        row = (
            await db.execute(
                select(PipelineForecast)
                .where(
                    PipelineForecast.workspace_id == current_user.workspace_id,
                    PipelineForecast.forecast_period == period,
                )
                .order_by(
                    PipelineForecast.forecast_date.desc(),
                    PipelineForecast.created_at.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        out[period.value] = _serialize_forecast(row) if row else None
    return out


@router.get("/pipeline/history")
async def report_pipeline_history(
    db: DbSession,
    current_user: CurrentUser,
    period: Annotated[ForecastPeriod, Query()] = ForecastPeriod.CURRENT_MONTH,
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(PipelineForecast)
            .where(
                PipelineForecast.workspace_id == current_user.workspace_id,
                PipelineForecast.forecast_period == period,
            )
            .order_by(PipelineForecast.forecast_date.asc())
        )
    ).scalars().all()
    return [_serialize_forecast(r) for r in rows]


@router.get("/pipeline/velocity")
async def report_pipeline_velocity(
    db: DbSession,
    current_user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=365)] = 90,
) -> dict[str, Any]:
    return await reporting_service.get_pipeline_velocity(
        db, current_user.workspace_id, days=days
    )


# --- revenue ---------------------------------------------------------------


@router.get("/revenue/by-month")
async def report_revenue_by_month(
    db: DbSession,
    current_user: CurrentUser,
    months: Annotated[int, Query(ge=1, le=36)] = 12,
) -> list[dict[str, Any]]:
    return await reporting_service.get_revenue_by_month(
        db, current_user.workspace_id, months=months
    )


@router.get("/revenue/by-rep")
async def report_revenue_by_rep(
    db: DbSession,
    current_user: User = Depends(require_manager_or_above()),
    days: Annotated[int, Query(ge=1, le=365)] = 90,
) -> list[dict[str, Any]]:
    return await reporting_service.get_revenue_by_rep(
        db, current_user.workspace_id, days=days
    )


@router.get("/revenue/by-source")
async def report_revenue_by_source(
    db: DbSession,
    current_user: CurrentUser,
    start_date: Annotated[datetime | None, Query()] = None,
    end_date: Annotated[datetime | None, Query()] = None,
) -> list[dict[str, Any]]:
    """Wraps the attribution service so the dashboard has one report surface."""
    return await get_source_report(
        db,
        workspace_id=current_user.workspace_id,
        start_date=start_date,
        end_date=end_date,
    )


# --- leads -----------------------------------------------------------------


@router.get("/leads/velocity")
async def report_leads_velocity(
    db: DbSession,
    current_user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    return await reporting_service.get_lead_velocity(
        db, current_user.workspace_id, days=days
    )


@router.get("/leads/by-source")
async def report_leads_by_source(
    db: DbSession,
    current_user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=365)] = 90,
) -> list[dict[str, Any]]:
    return await reporting_service.get_leads_by_source(
        db, current_user.workspace_id, days=days
    )


@router.get("/leads/{lead_id}/score-trend")
async def report_lead_score_trend(
    lead_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[dict[str, Any]]:
    lead = (
        await db.execute(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.workspace_id == current_user.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found"
        )
    return await reporting_service.get_lead_score_trend(
        db, current_user.workspace_id, lead_id, days=days
    )


# --- rep performance -------------------------------------------------------


@router.get("/reps")
async def report_reps(
    db: DbSession,
    current_user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[dict[str, Any]]:
    return await reporting_service.get_rep_performance(
        db, current_user.workspace_id, days=days
    )


@router.get("/reps/{user_id}")
async def report_rep_detail(
    user_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    rows = await reporting_service.get_rep_performance(
        db, current_user.workspace_id, days=days
    )
    match = next((r for r in rows if r["user_id"] == str(user_id)), None)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rep not found"
        )
    pipeline = await reporting_service.get_pipeline_summary(
        db, current_user.workspace_id, owner_id=user_id
    )
    win_rate = await reporting_service.get_win_rate(
        db, current_user.workspace_id, days=days, owner_id=user_id
    )
    activity = await reporting_service.get_activity_summary(
        db, current_user.workspace_id, days=days, owner_id=user_id
    )
    return {
        "summary": match,
        "pipeline": pipeline,
        "win_rate": win_rate,
        "activity": activity,
    }


# --- activity --------------------------------------------------------------


@router.get("/activity")
async def report_activity(
    db: DbSession,
    current_user: CurrentUser,
    owner_id: UUID | None = None,
    days: Annotated[int, Query(ge=1, le=365)] = 7,
) -> dict[str, Any]:
    return await reporting_service.get_activity_summary(
        db, current_user.workspace_id, days=days, owner_id=owner_id
    )


# --- dashboard -------------------------------------------------------------


@router.get("/dashboard")
async def report_dashboard(
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Single fast endpoint backed by DashboardMetricCache."""
    return await reporting_service.get_cached_dashboard(
        db, current_user.workspace_id
    )


def _serialize_forecast(row: PipelineForecast) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "forecast_period": row.forecast_period.value,
        "forecast_date": row.forecast_date.isoformat(),
        "forecast_value_cents": row.forecast_value_cents,
        "pipeline_value_cents": row.pipeline_value_cents,
        "deal_count": row.deal_count,
        "won_deal_count": row.won_deal_count,
        "won_value_cents": row.won_value_cents,
        "at_risk_deal_ids": row.at_risk_deal_ids or [],
        "recommendations": row.recommendations or [],
        "agent_run_id": str(row.agent_run_id) if row.agent_run_id else None,
        "created_at": row.created_at.isoformat(),
    }
