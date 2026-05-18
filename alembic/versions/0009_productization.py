"""Productization: plans, workspace_subscriptions, api_keys, onboarding_checklists, partner_referrals.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(*values: str, name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


subscription_status_enum = _enum(
    "trialing", "active", "past_due", "cancelled", "paused",
    name="subscription_status",
)
partner_referral_status_enum = _enum(
    "pending", "signed_up", "paying", "churned",
    name="partner_referral_status",
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

    subscription_status_enum.create(bind, checkfirst=True)
    partner_referral_status_enum.create(bind, checkfirst=True)

    # --- plans -------------------------------------------------------------
    op.create_table(
        "plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("price_cents_monthly", sa.Integer(), nullable=False),
        sa.Column("price_cents_annual", sa.Integer(), nullable=False),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("max_contacts", sa.Integer(), nullable=True),
        sa.Column(
            "includes_netsuite", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "includes_ai_agents", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column("stripe_price_id_monthly", sa.String(length=255), nullable=True),
        sa.Column("stripe_price_id_annual", sa.String(length=255), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column(
            "is_public", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        *_timestamp_cols(),
        sa.UniqueConstraint("slug", name="uq_plans_slug"),
    )

    # --- workspace_subscriptions ------------------------------------------
    op.create_table(
        "workspace_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status", subscription_status_enum,
            nullable=False, server_default="trialing",
        ),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "current_period_start", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "current_period_end", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("billing_email", sa.String(length=255), nullable=True),
        sa.Column("billing_name", sa.String(length=255), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_workspace_subscriptions_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"],
            ondelete="RESTRICT",
            name="fk_workspace_subscriptions_plan_id",
        ),
        sa.UniqueConstraint(
            "workspace_id", name="uq_workspace_subscriptions_workspace"
        ),
    )
    op.create_index(
        "ix_workspace_subscriptions_status",
        "workspace_subscriptions",
        ["status"],
    )

    # --- api_keys ----------------------------------------------------------
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=10), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column("scopes", postgresql.JSON(), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_api_keys_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            ondelete="CASCADE",
            name="fk_api_keys_created_by_id",
        ),
    )
    op.create_index("ix_api_keys_workspace_id", "api_keys", ["workspace_id"])
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])

    # --- onboarding_checklists --------------------------------------------
    op.create_table(
        "onboarding_checklists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "invite_team_member", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "connect_email", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "connect_twilio", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "import_contacts", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "create_first_deal", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "configure_pipeline", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "set_up_workflow", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "connect_netsuite", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "install_tracking_snippet", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_onboarding_checklists_workspace_id",
        ),
        sa.UniqueConstraint(
            "workspace_id", name="uq_onboarding_checklists_workspace"
        ),
    )

    # --- partner_referrals -------------------------------------------------
    op.create_table(
        "partner_referrals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("partner_name", sa.String(length=255), nullable=False),
        sa.Column("partner_email", sa.String(length=255), nullable=False),
        sa.Column("referral_code", sa.String(length=50), nullable=False),
        sa.Column(
            "referred_workspace_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "status", partner_referral_status_enum,
            nullable=False, server_default="pending",
        ),
        sa.Column(
            "commission_rate", sa.Numeric(5, 2),
            nullable=False, server_default="20.00",
        ),
        sa.Column(
            "commission_paid_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["referred_workspace_id"], ["workspaces.id"],
            ondelete="SET NULL",
            name="fk_partner_referrals_referred_workspace_id",
        ),
        sa.UniqueConstraint(
            "referral_code", name="uq_partner_referrals_referral_code"
        ),
    )
    op.create_index(
        "ix_partner_referrals_referral_code",
        "partner_referrals",
        ["referral_code"],
    )

    # --- seed default plans ------------------------------------------------
    op.execute(
        """
        INSERT INTO plans (
            id, name, slug, price_cents_monthly, price_cents_annual,
            max_users, max_contacts, includes_netsuite, includes_ai_agents,
            is_active, is_public
        ) VALUES
        (
            gen_random_uuid(), 'Starter', 'starter', 7500, 75000,
            5, NULL, FALSE, TRUE, TRUE, TRUE
        ),
        (
            gen_random_uuid(), 'Growth', 'growth', 8500, 85000,
            25, NULL, TRUE, TRUE, TRUE, TRUE
        ),
        (
            gen_random_uuid(), 'Enterprise', 'enterprise', 9500, 95000,
            NULL, NULL, TRUE, TRUE, TRUE, TRUE
        )
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index(
        "ix_partner_referrals_referral_code", table_name="partner_referrals"
    )
    op.drop_table("partner_referrals")

    op.drop_table("onboarding_checklists")

    op.drop_index("ix_api_keys_key_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_workspace_id", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index(
        "ix_workspace_subscriptions_status",
        table_name="workspace_subscriptions",
    )
    op.drop_table("workspace_subscriptions")

    op.drop_table("plans")

    partner_referral_status_enum.drop(bind, checkfirst=True)
    subscription_status_enum.drop(bind, checkfirst=True)
