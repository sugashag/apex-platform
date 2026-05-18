"""Intelligence & Reporting: lead_score_history, pipeline_forecasts, dashboard_metric_cache.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(*values: str, name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


forecast_period_enum = _enum(
    "current_month",
    "next_month",
    "current_quarter",
    name="forecast_period",
)


def _timestamp_cols() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()

    # --- enums --------------------------------------------------------------
    forecast_period_enum.create(bind, checkfirst=True)

    # --- lead_score_history -------------------------------------------------
    op.create_table(
        "lead_score_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("score_rationale", sa.Text(), nullable=True),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_lead_score_history_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"],
            ondelete="CASCADE",
            name="fk_lead_score_history_lead_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="CASCADE",
            name="fk_lead_score_history_contact_id",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"],
            ondelete="SET NULL",
            name="fk_lead_score_history_agent_run_id",
        ),
    )
    op.create_index(
        "ix_lead_score_history_workspace_lead_created",
        "lead_score_history",
        ["workspace_id", "lead_id", "created_at"],
    )

    # --- pipeline_forecasts -------------------------------------------------
    op.create_table(
        "pipeline_forecasts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("forecast_period", forecast_period_enum, nullable=False),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("forecast_value_cents", sa.BigInteger(), nullable=False),
        sa.Column("pipeline_value_cents", sa.BigInteger(), nullable=False),
        sa.Column("deal_count", sa.Integer(), nullable=False),
        sa.Column("won_deal_count", sa.Integer(), nullable=True),
        sa.Column("won_value_cents", sa.BigInteger(), nullable=True),
        sa.Column(
            "at_risk_deal_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "recommendations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_pipeline_forecasts_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"],
            ondelete="SET NULL",
            name="fk_pipeline_forecasts_agent_run_id",
        ),
    )
    op.create_index(
        "ix_pipeline_forecasts_workspace_period_date",
        "pipeline_forecasts",
        ["workspace_id", "forecast_period", "forecast_date"],
    )

    # --- dashboard_metric_cache --------------------------------------------
    op.create_table(
        "dashboard_metric_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_key", sa.String(length=100), nullable=False),
        sa.Column(
            "metric_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_dashboard_metric_cache_workspace_id",
        ),
        sa.UniqueConstraint(
            "workspace_id", "metric_key",
            name="uq_dashboard_metric_cache_workspace_key",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_table("dashboard_metric_cache")

    op.drop_index(
        "ix_pipeline_forecasts_workspace_period_date",
        table_name="pipeline_forecasts",
    )
    op.drop_table("pipeline_forecasts")

    op.drop_index(
        "ix_lead_score_history_workspace_lead_created",
        table_name="lead_score_history",
    )
    op.drop_table("lead_score_history")

    forecast_period_enum.drop(bind, checkfirst=True)
