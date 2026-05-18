"""Workflows: workflows, conditions, steps, runs, step_runs, sequences, sequence_steps, sequence_enrollments.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(*values: str, name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


workflow_trigger_type_enum = _enum(
    "lead_created",
    "lead_status_changed",
    "deal_stage_changed",
    "deal_created",
    "form_submitted",
    "call_completed",
    "email_received",
    "contact_created",
    "payment_received",
    "sla_breached",
    "manual",
    name="workflow_trigger_type",
)

workflow_condition_operator_enum = _enum(
    "equals",
    "not_equals",
    "greater_than",
    "less_than",
    "contains",
    "not_contains",
    "is_set",
    "is_not_set",
    name="workflow_condition_operator",
)

workflow_action_type_enum = _enum(
    "send_email",
    "send_sms",
    "create_task",
    "assign_owner",
    "update_field",
    "add_tag",
    "notify_user",
    "wait",
    "human_gate",
    "trigger_agent",
    "create_activity",
    "change_deal_stage",
    name="workflow_action_type",
)

workflow_run_status_enum = _enum(
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
    name="workflow_run_status",
)

workflow_step_run_status_enum = _enum(
    "pending",
    "running",
    "waiting_approval",
    "approved",
    "skipped",
    "completed",
    "failed",
    name="workflow_step_run_status",
)

sequence_step_type_enum = _enum(
    "email",
    "sms",
    "call_task",
    "ai_draft_email",
    name="sequence_step_type",
)

sequence_enrollment_status_enum = _enum(
    "active",
    "completed",
    "exited_reply",
    "exited_manual",
    "paused",
    name="sequence_enrollment_status",
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

    # --- enums ---------------------------------------------------------------
    workflow_trigger_type_enum.create(bind, checkfirst=True)
    workflow_condition_operator_enum.create(bind, checkfirst=True)
    workflow_action_type_enum.create(bind, checkfirst=True)
    workflow_run_status_enum.create(bind, checkfirst=True)
    workflow_step_run_status_enum.create(bind, checkfirst=True)
    sequence_step_type_enum.create(bind, checkfirst=True)
    sequence_enrollment_status_enum.create(bind, checkfirst=True)

    # --- workflows -----------------------------------------------------------
    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("trigger_type", workflow_trigger_type_enum, nullable=False),
        sa.Column(
            "trigger_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_workflows_workspace_id",
        ),
    )
    op.create_index("ix_workflows_workspace_id", "workflows", ["workspace_id"])
    op.create_index("ix_workflows_trigger_type", "workflows", ["trigger_type"])
    op.create_index("ix_workflows_is_active", "workflows", ["is_active"])

    # --- workflow_conditions -------------------------------------------------
    op.create_table(
        "workflow_conditions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field", sa.String(length=100), nullable=False),
        sa.Column("operator", workflow_condition_operator_enum, nullable=False),
        sa.Column("value", sa.String(length=500), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflows.id"],
            ondelete="CASCADE",
            name="fk_workflow_conditions_workflow_id",
        ),
    )
    op.create_index(
        "ix_workflow_conditions_workflow_id",
        "workflow_conditions",
        ["workflow_id"],
    )

    # --- workflow_steps ------------------------------------------------------
    op.create_table(
        "workflow_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("action_type", workflow_action_type_enum, nullable=False),
        sa.Column(
            "action_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "delay_minutes", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflows.id"],
            ondelete="CASCADE",
            name="fk_workflow_steps_workflow_id",
        ),
    )
    op.create_index("ix_workflow_steps_workflow_id", "workflow_steps", ["workflow_id"])
    op.create_index("ix_workflow_steps_position", "workflow_steps", ["position"])

    # --- workflow_runs -------------------------------------------------------
    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_type", sa.String(length=100), nullable=False),
        sa.Column("trigger_entity_type", sa.String(length=50), nullable=True),
        sa.Column("trigger_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status", workflow_run_status_enum, nullable=False, server_default="running"
        ),
        sa.Column(
            "current_step_position",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_workflow_runs_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflows.id"],
            ondelete="CASCADE",
            name="fk_workflow_runs_workflow_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="SET NULL",
            name="fk_workflow_runs_contact_id",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.id"],
            ondelete="SET NULL",
            name="fk_workflow_runs_deal_id",
        ),
    )
    op.create_index("ix_workflow_runs_workspace_id", "workflow_runs", ["workspace_id"])
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])
    op.create_index("ix_workflow_runs_contact_id", "workflow_runs", ["contact_id"])

    # --- workflow_step_runs --------------------------------------------------
    op.create_table(
        "workflow_step_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            workflow_step_run_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execute_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "output", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"],
            ondelete="CASCADE",
            name="fk_workflow_step_runs_workflow_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_step_id"], ["workflow_steps.id"],
            ondelete="CASCADE",
            name="fk_workflow_step_runs_workflow_step_id",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"], ["users.id"],
            ondelete="SET NULL",
            name="fk_workflow_step_runs_approved_by_id",
        ),
    )
    op.create_index(
        "ix_workflow_step_runs_workflow_run_id",
        "workflow_step_runs",
        ["workflow_run_id"],
    )
    op.create_index(
        "ix_workflow_step_runs_status", "workflow_step_runs", ["status"]
    )
    op.create_index(
        "ix_workflow_step_runs_execute_at", "workflow_step_runs", ["execute_at"]
    )

    # --- sequences -----------------------------------------------------------
    op.create_table(
        "sequences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "exit_on_reply", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_sequences_workspace_id",
        ),
    )
    op.create_index("ix_sequences_workspace_id", "sequences", ["workspace_id"])

    # --- sequence_steps ------------------------------------------------------
    op.create_table(
        "sequence_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("step_type", sequence_step_type_enum, nullable=False),
        sa.Column("delay_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subject_template", sa.String(length=500), nullable=True),
        sa.Column("body_template", sa.Text(), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["sequence_id"], ["sequences.id"],
            ondelete="CASCADE",
            name="fk_sequence_steps_sequence_id",
        ),
    )
    op.create_index(
        "ix_sequence_steps_sequence_id", "sequence_steps", ["sequence_id"]
    )
    op.create_index("ix_sequence_steps_position", "sequence_steps", ["position"])

    # --- sequence_enrollments ------------------------------------------------
    op.create_table(
        "sequence_enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("enrolled_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sequence_enrollment_status_enum,
            nullable=False,
            server_default="active",
        ),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_step_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_sequence_enrollments_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["sequence_id"], ["sequences.id"],
            ondelete="CASCADE",
            name="fk_sequence_enrollments_sequence_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="CASCADE",
            name="fk_sequence_enrollments_contact_id",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.id"],
            ondelete="SET NULL",
            name="fk_sequence_enrollments_deal_id",
        ),
        sa.ForeignKeyConstraint(
            ["enrolled_by_id"], ["users.id"],
            ondelete="SET NULL",
            name="fk_sequence_enrollments_enrolled_by_id",
        ),
    )
    op.create_index(
        "ix_sequence_enrollments_workspace_id",
        "sequence_enrollments",
        ["workspace_id"],
    )
    op.create_index(
        "ix_sequence_enrollments_sequence_id",
        "sequence_enrollments",
        ["sequence_id"],
    )
    op.create_index(
        "ix_sequence_enrollments_contact_id",
        "sequence_enrollments",
        ["contact_id"],
    )
    op.create_index(
        "ix_sequence_enrollments_status", "sequence_enrollments", ["status"]
    )
    op.create_index(
        "ix_sequence_enrollments_next_step_at",
        "sequence_enrollments",
        ["next_step_at"],
    )
    # Partial unique index so a contact is in any given sequence at most once
    # while the enrollment is still active. Completed/exited enrollments don't
    # block re-enrollment.
    op.create_index(
        "uq_sequence_enrollments_active",
        "sequence_enrollments",
        ["sequence_id", "contact_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index(
        "uq_sequence_enrollments_active", table_name="sequence_enrollments"
    )
    op.drop_index(
        "ix_sequence_enrollments_next_step_at",
        table_name="sequence_enrollments",
    )
    op.drop_index(
        "ix_sequence_enrollments_status", table_name="sequence_enrollments"
    )
    op.drop_index(
        "ix_sequence_enrollments_contact_id",
        table_name="sequence_enrollments",
    )
    op.drop_index(
        "ix_sequence_enrollments_sequence_id",
        table_name="sequence_enrollments",
    )
    op.drop_index(
        "ix_sequence_enrollments_workspace_id",
        table_name="sequence_enrollments",
    )
    op.drop_table("sequence_enrollments")

    op.drop_index("ix_sequence_steps_position", table_name="sequence_steps")
    op.drop_index("ix_sequence_steps_sequence_id", table_name="sequence_steps")
    op.drop_table("sequence_steps")

    op.drop_index("ix_sequences_workspace_id", table_name="sequences")
    op.drop_table("sequences")

    op.drop_index(
        "ix_workflow_step_runs_execute_at", table_name="workflow_step_runs"
    )
    op.drop_index(
        "ix_workflow_step_runs_status", table_name="workflow_step_runs"
    )
    op.drop_index(
        "ix_workflow_step_runs_workflow_run_id",
        table_name="workflow_step_runs",
    )
    op.drop_table("workflow_step_runs")

    op.drop_index("ix_workflow_runs_contact_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_workflow_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_workspace_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_index("ix_workflow_steps_position", table_name="workflow_steps")
    op.drop_index("ix_workflow_steps_workflow_id", table_name="workflow_steps")
    op.drop_table("workflow_steps")

    op.drop_index(
        "ix_workflow_conditions_workflow_id", table_name="workflow_conditions"
    )
    op.drop_table("workflow_conditions")

    op.drop_index("ix_workflows_is_active", table_name="workflows")
    op.drop_index("ix_workflows_trigger_type", table_name="workflows")
    op.drop_index("ix_workflows_workspace_id", table_name="workflows")
    op.drop_table("workflows")

    sequence_enrollment_status_enum.drop(bind, checkfirst=True)
    sequence_step_type_enum.drop(bind, checkfirst=True)
    workflow_step_run_status_enum.drop(bind, checkfirst=True)
    workflow_run_status_enum.drop(bind, checkfirst=True)
    workflow_action_type_enum.drop(bind, checkfirst=True)
    workflow_condition_operator_enum.drop(bind, checkfirst=True)
    workflow_trigger_type_enum.drop(bind, checkfirst=True)
