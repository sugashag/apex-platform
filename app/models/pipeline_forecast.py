"""PipelineForecast — AI-generated revenue forecast snapshot per workspace + period."""

import enum
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class ForecastPeriod(enum.StrEnum):
    CURRENT_MONTH = "current_month"
    NEXT_MONTH = "next_month"
    CURRENT_QUARTER = "current_quarter"


class PipelineForecast(Base):
    """A snapshot of AI-generated pipeline expectations + recommendations."""

    __tablename__ = "pipeline_forecasts"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    forecast_period: Mapped[ForecastPeriod] = mapped_column(
        pg_enum(ForecastPeriod, name="forecast_period"),
        nullable=False,
    )
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False)
    forecast_value_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pipeline_value_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Backfilled at period end:
    won_deal_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    won_value_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    at_risk_deal_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    recommendations: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index(
            "ix_pipeline_forecasts_workspace_period_date",
            "workspace_id",
            "forecast_period",
            "forecast_date",
        ),
    )
