"""Pipeline forecast endpoints — generate, list, fetch latest."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.agents.pipeline_forecaster import PipelineForecasterAgent
from app.dependencies import CurrentUser, DbSession
from app.models.pipeline_forecast import ForecastPeriod, PipelineForecast

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


def _serialize(row: PipelineForecast) -> dict[str, Any]:
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


@router.post("/generate", status_code=status.HTTP_201_CREATED)
async def generate_forecast(
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Manually trigger the pipeline forecaster agent for this workspace."""
    agent = PipelineForecasterAgent()
    run = await agent.execute(
        db,
        workspace_id=current_user.workspace_id,
        entity_id=None,
        entity_type="workspace",
        trigger="manual",
    )
    await db.commit()

    forecasts = (
        await db.execute(
            select(PipelineForecast)
            .where(
                PipelineForecast.workspace_id == current_user.workspace_id,
                PipelineForecast.agent_run_id == run.id,
            )
            .order_by(PipelineForecast.forecast_period.asc())
        )
    ).scalars().all()
    return {
        "agent_run_id": str(run.id),
        "status": run.status.value,
        "forecasts": [_serialize(f) for f in forecasts],
    }


@router.get("")
async def list_forecasts(
    db: DbSession,
    current_user: CurrentUser,
    period: Annotated[ForecastPeriod | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    stmt = select(PipelineForecast).where(
        PipelineForecast.workspace_id == current_user.workspace_id
    )
    if period is not None:
        stmt = stmt.where(PipelineForecast.forecast_period == period)
    stmt = stmt.order_by(
        PipelineForecast.forecast_date.desc(),
        PipelineForecast.created_at.desc(),
    ).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


@router.get("/latest")
async def latest_forecast(
    db: DbSession,
    current_user: CurrentUser,
    period: Annotated[ForecastPeriod, Query()] = ForecastPeriod.CURRENT_MONTH,
) -> dict[str, Any] | None:
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
    return _serialize(row) if row else None
