"""Communications: email_accounts, threads, messages, calls, sms_messages, assignment_rules.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(*values: str, name: str) -> postgresql.ENUM:
    """ENUM declared with `create_type=False` so it is only emitted by the
    explicit `.create(bind, checkfirst=True)` calls in upgrade()."""
    return postgresql.ENUM(*values, name=name, create_type=False)


email_provider_enum = _enum("google", "microsoft", name="email_provider")
thread_status_enum = _enum("open", "snoozed", "resolved", name="thread_status")
message_direction_enum = _enum("inbound", "outbound", name="message_direction")
call_direction_enum = _enum("inbound", "outbound", name="call_direction")
call_status_enum = _enum(
    "initiated",
    "ringing",
    "in_progress",
    "completed",
    "failed",
    "no_answer",
    "busy",
    "canceled",
    name="call_status",
)
call_sentiment_enum = _enum("positive", "neutral", "negative", name="call_sentiment")
call_handled_by_enum = _enum(
    "ai_agent", "human", "ai_then_human", name="call_handled_by"
)
sms_direction_enum = _enum("inbound", "outbound", name="sms_direction")
sms_status_enum = _enum(
    "queued", "sent", "delivered", "failed", "received", name="sms_status"
)
assignment_condition_operator_enum = _enum(
    "equals", "contains", "starts_with", "ends_with",
    name="assignment_condition_operator",
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

    # --- enums ----------------------------------------------------------------
    email_provider_enum.create(bind, checkfirst=True)
    thread_status_enum.create(bind, checkfirst=True)
    message_direction_enum.create(bind, checkfirst=True)
    call_direction_enum.create(bind, checkfirst=True)
    call_status_enum.create(bind, checkfirst=True)
    call_sentiment_enum.create(bind, checkfirst=True)
    call_handled_by_enum.create(bind, checkfirst=True)
    sms_direction_enum.create(bind, checkfirst=True)
    sms_status_enum.create(bind, checkfirst=True)
    assignment_condition_operator_enum.create(bind, checkfirst=True)

    # --- email_accounts -------------------------------------------------------
    op.create_table(
        "email_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_address", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("provider", email_provider_enum, nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_email_accounts_workspace_id",
        ),
        sa.UniqueConstraint(
            "workspace_id", "email_address",
            name="uq_email_accounts_workspace_email",
        ),
    )
    op.create_index(
        "ix_email_accounts_workspace_id", "email_accounts", ["workspace_id"]
    )

    # --- threads --------------------------------------------------------------
    op.create_table(
        "threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", thread_status_enum, nullable=False, server_default="open"),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sla_first_response_due_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("sla_resolution_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_thread_id", sa.String(length=500), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_threads_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="SET NULL",
            name="fk_threads_contact_id",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.id"],
            ondelete="SET NULL",
            name="fk_threads_deal_id",
        ),
        sa.ForeignKeyConstraint(
            ["email_account_id"], ["email_accounts.id"],
            ondelete="SET NULL",
            name="fk_threads_email_account_id",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["users.id"],
            ondelete="SET NULL",
            name="fk_threads_assignee_id",
        ),
    )
    op.create_index("ix_threads_workspace_id", "threads", ["workspace_id"])
    op.create_index("ix_threads_contact_id", "threads", ["contact_id"])
    op.create_index("ix_threads_deal_id", "threads", ["deal_id"])
    op.create_index("ix_threads_assignee_id", "threads", ["assignee_id"])
    op.create_index("ix_threads_status", "threads", ["status"])

    # --- messages -------------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_email", sa.String(length=255), nullable=False),
        sa.Column("from_name", sa.String(length=255), nullable=True),
        sa.Column("to_emails", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cc_emails", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("direction", message_direction_enum, nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("external_message_id", sa.String(length=500), nullable=True),
        sa.Column("resend_message_id", sa.String(length=255), nullable=True),
        sa.Column("ai_draft", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_messages_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["threads.id"],
            ondelete="CASCADE",
            name="fk_messages_thread_id",
        ),
    )
    op.create_index("ix_messages_workspace_id", "messages", ["workspace_id"])
    op.create_index("ix_messages_thread_id", "messages", ["thread_id"])
    op.create_index("ix_messages_direction", "messages", ["direction"])
    op.create_index("ix_messages_sent_at", "messages", ["sent_at"])

    # --- calls ----------------------------------------------------------------
    op.create_table(
        "calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("initiated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("twilio_call_sid", sa.String(length=100), nullable=True),
        sa.Column("direction", call_direction_enum, nullable=False),
        sa.Column(
            "status", call_status_enum, nullable=False, server_default="initiated"
        ),
        sa.Column("from_number", sa.String(length=30), nullable=True),
        sa.Column("to_number", sa.String(length=30), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("recording_url", sa.String(length=500), nullable=True),
        sa.Column("recording_sid", sa.String(length=100), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("ai_sentiment", call_sentiment_enum, nullable=True),
        sa.Column("ai_next_action", sa.Text(), nullable=True),
        sa.Column(
            "handled_by", call_handled_by_enum, nullable=False, server_default="human"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_calls_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="SET NULL",
            name="fk_calls_contact_id",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.id"],
            ondelete="SET NULL",
            name="fk_calls_deal_id",
        ),
        sa.ForeignKeyConstraint(
            ["initiated_by_id"], ["users.id"],
            ondelete="SET NULL",
            name="fk_calls_initiated_by_id",
        ),
        sa.UniqueConstraint("twilio_call_sid", name="uq_calls_twilio_call_sid"),
    )
    op.create_index("ix_calls_workspace_id", "calls", ["workspace_id"])
    op.create_index("ix_calls_contact_id", "calls", ["contact_id"])
    op.create_index("ix_calls_deal_id", "calls", ["deal_id"])
    op.create_index("ix_calls_status", "calls", ["status"])
    op.create_index("ix_calls_started_at", "calls", ["started_at"])

    # --- sms_messages ---------------------------------------------------------
    op.create_table(
        "sms_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("twilio_message_sid", sa.String(length=100), nullable=True),
        sa.Column("direction", sms_direction_enum, nullable=False),
        sa.Column("from_number", sa.String(length=30), nullable=False),
        sa.Column("to_number", sa.String(length=30), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sms_status_enum, nullable=False, server_default="queued"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_sms_messages_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="SET NULL",
            name="fk_sms_messages_contact_id",
        ),
        sa.UniqueConstraint(
            "twilio_message_sid", name="uq_sms_messages_twilio_message_sid"
        ),
    )
    op.create_index("ix_sms_messages_workspace_id", "sms_messages", ["workspace_id"])
    op.create_index("ix_sms_messages_contact_id", "sms_messages", ["contact_id"])
    op.create_index("ix_sms_messages_direction", "sms_messages", ["direction"])

    # --- assignment_rules -----------------------------------------------------
    op.create_table(
        "assignment_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("condition_field", sa.String(length=100), nullable=False),
        sa.Column(
            "condition_operator", assignment_condition_operator_enum, nullable=False
        ),
        sa.Column("condition_value", sa.String(length=500), nullable=False),
        sa.Column("assign_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_assignment_rules_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["assign_to_user_id"], ["users.id"],
            ondelete="SET NULL",
            name="fk_assignment_rules_assign_to_user_id",
        ),
    )
    op.create_index(
        "ix_assignment_rules_workspace_id", "assignment_rules", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assignment_rules_workspace_id", table_name="assignment_rules"
    )
    op.drop_table("assignment_rules")

    op.drop_index("ix_sms_messages_direction", table_name="sms_messages")
    op.drop_index("ix_sms_messages_contact_id", table_name="sms_messages")
    op.drop_index("ix_sms_messages_workspace_id", table_name="sms_messages")
    op.drop_table("sms_messages")

    op.drop_index("ix_calls_started_at", table_name="calls")
    op.drop_index("ix_calls_status", table_name="calls")
    op.drop_index("ix_calls_deal_id", table_name="calls")
    op.drop_index("ix_calls_contact_id", table_name="calls")
    op.drop_index("ix_calls_workspace_id", table_name="calls")
    op.drop_table("calls")

    op.drop_index("ix_messages_sent_at", table_name="messages")
    op.drop_index("ix_messages_direction", table_name="messages")
    op.drop_index("ix_messages_thread_id", table_name="messages")
    op.drop_index("ix_messages_workspace_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_threads_status", table_name="threads")
    op.drop_index("ix_threads_assignee_id", table_name="threads")
    op.drop_index("ix_threads_deal_id", table_name="threads")
    op.drop_index("ix_threads_contact_id", table_name="threads")
    op.drop_index("ix_threads_workspace_id", table_name="threads")
    op.drop_table("threads")

    op.drop_index("ix_email_accounts_workspace_id", table_name="email_accounts")
    op.drop_table("email_accounts")

    bind = op.get_bind()
    assignment_condition_operator_enum.drop(bind, checkfirst=True)
    sms_status_enum.drop(bind, checkfirst=True)
    sms_direction_enum.drop(bind, checkfirst=True)
    call_handled_by_enum.drop(bind, checkfirst=True)
    call_sentiment_enum.drop(bind, checkfirst=True)
    call_status_enum.drop(bind, checkfirst=True)
    call_direction_enum.drop(bind, checkfirst=True)
    message_direction_enum.drop(bind, checkfirst=True)
    thread_status_enum.drop(bind, checkfirst=True)
    email_provider_enum.drop(bind, checkfirst=True)
