"""AI layer: agent_runs and ai_drafts.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(*values: str, name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


agent_type_enum = _enum(
    "lead_scorer",
    "call_summarizer",
    "outbound_drafter",
    "reply_drafter",
    "ticket_router",
    "objection_handler",
    "pipeline_forecaster",
    name="agent_type",
)
agent_run_status_enum = _enum(
    "running", "completed", "failed", name="agent_run_status"
)
ai_draft_type_enum = _enum(
    "email_reply", "outbound_email", "call_script", name="ai_draft_type"
)
ai_draft_status_enum = _enum(
    "pending", "approved", "edited_and_sent", "discarded", name="ai_draft_status"
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

    agent_type_enum.create(bind, checkfirst=True)
    agent_run_status_enum.create(bind, checkfirst=True)
    ai_draft_type_enum.create(bind, checkfirst=True)
    ai_draft_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_type", agent_type_enum, nullable=False),
        sa.Column("trigger", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("model_used", sa.String(length=100), nullable=True),
        sa.Column(
            "status",
            agent_run_status_enum,
            nullable=False,
            server_default="running",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_agent_runs_workspace_id",
        ),
    )
    op.create_index("ix_agent_runs_workspace_id", "agent_runs", ["workspace_id"])
    op.create_index("ix_agent_runs_agent_type", "agent_runs", ["agent_type"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("ix_agent_runs_created_at", "agent_runs", ["created_at"])

    op.create_table(
        "ai_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("draft_type", ai_draft_type_enum, nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column(
            "status",
            ai_draft_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_ai_drafts_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"],
            ondelete="SET NULL",
            name="fk_ai_drafts_agent_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"], ["users.id"],
            ondelete="SET NULL",
            name="fk_ai_drafts_reviewed_by_id",
        ),
    )
    op.create_index("ix_ai_drafts_workspace_id", "ai_drafts", ["workspace_id"])
    op.create_index("ix_ai_drafts_draft_type", "ai_drafts", ["draft_type"])
    op.create_index("ix_ai_drafts_status", "ai_drafts", ["status"])
    op.create_index("ix_ai_drafts_entity_id", "ai_drafts", ["entity_id"])


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_ai_drafts_entity_id", table_name="ai_drafts")
    op.drop_index("ix_ai_drafts_status", table_name="ai_drafts")
    op.drop_index("ix_ai_drafts_draft_type", table_name="ai_drafts")
    op.drop_index("ix_ai_drafts_workspace_id", table_name="ai_drafts")
    op.drop_table("ai_drafts")

    op.drop_index("ix_agent_runs_created_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_type", table_name="agent_runs")
    op.drop_index("ix_agent_runs_workspace_id", table_name="agent_runs")
    op.drop_table("agent_runs")

    ai_draft_status_enum.drop(bind, checkfirst=True)
    ai_draft_type_enum.drop(bind, checkfirst=True)
    agent_run_status_enum.drop(bind, checkfirst=True)
    agent_type_enum.drop(bind, checkfirst=True)
