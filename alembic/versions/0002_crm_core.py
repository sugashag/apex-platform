"""CRM core: companies, pipeline_stages, contacts, deals, leads, activities.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(*values: str, name: str) -> postgresql.ENUM:
    """ENUM declared with `create_type=False` so it is only emitted by the
    explicit `.create(bind, checkfirst=True)` calls in upgrade()."""
    return postgresql.ENUM(*values, name=name, create_type=False)


email_status_enum = _enum("active", "bounced", "unsubscribed", name="email_status")
lead_status_enum = _enum(
    "new", "working", "qualified", "disqualified", "converted",
    name="lead_status",
)
deal_close_reason_enum = _enum(
    "won", "lost", "no_decision",
    name="deal_close_reason",
)
activity_type_enum = _enum(
    "call",
    "email_sent",
    "email_received",
    "note",
    "stage_change",
    "score_update",
    "payment",
    "sms",
    "meeting",
    "task",
    name="activity_type",
)
activity_actor_type_enum = _enum("human", "ai_agent", name="activity_actor_type")


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
    email_status_enum.create(bind, checkfirst=True)
    lead_status_enum.create(bind, checkfirst=True)
    deal_close_reason_enum.create(bind, checkfirst=True)
    activity_type_enum.create(bind, checkfirst=True)
    activity_actor_type_enum.create(bind, checkfirst=True)

    # --- companies ------------------------------------------------------------
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("annual_revenue_cents", sa.BigInteger(), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("linkedin_url", sa.String(length=500), nullable=True),
        sa.Column("netsuite_internal_id", sa.String(length=50), nullable=True),
        sa.Column("netsuite_external_id", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_companies_workspace_id",
        ),
    )
    op.create_index("ix_companies_workspace_id", "companies", ["workspace_id"])
    op.create_index(
        "uq_companies_workspace_domain",
        "companies",
        ["workspace_id", "domain"],
        unique=True,
        postgresql_where=sa.text("domain IS NOT NULL"),
    )

    # --- pipeline_stages ------------------------------------------------------
    op.create_table(
        "pipeline_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "probability_default", sa.Integer(),
            nullable=False, server_default=sa.text("0"),
        ),
        sa.Column("is_won", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_lost", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("color", sa.String(length=7), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_pipeline_stages_workspace_id",
        ),
        sa.UniqueConstraint(
            "workspace_id", "position",
            name="uq_pipeline_stages_workspace_position",
        ),
    )
    op.create_index(
        "ix_pipeline_stages_workspace_id", "pipeline_stages", ["workspace_id"]
    )

    # --- contacts -------------------------------------------------------------
    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=150), nullable=True),
        sa.Column("lead_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("source_campaign", sa.String(length=255), nullable=True),
        sa.Column("source_medium", sa.String(length=100), nullable=True),
        sa.Column("source_term", sa.String(length=255), nullable=True),
        sa.Column("source_content", sa.String(length=255), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_status", email_status_enum, nullable=False, server_default="active"),
        sa.Column("netsuite_internal_id", sa.String(length=50), nullable=True),
        sa.Column("netsuite_external_id", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_contacts_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"],
            ondelete="SET NULL",
            name="fk_contacts_company_id",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"],
            ondelete="SET NULL",
            name="fk_contacts_owner_id",
        ),
        sa.UniqueConstraint("workspace_id", "email", name="uq_contacts_workspace_email"),
    )
    op.create_index("ix_contacts_workspace_id", "contacts", ["workspace_id"])
    op.create_index("ix_contacts_company_id", "contacts", ["company_id"])
    op.create_index("ix_contacts_owner_id", "contacts", ["owner_id"])
    op.create_index("ix_contacts_lead_score", "contacts", ["lead_score"])
    op.create_index("ix_contacts_source", "contacts", ["source"])

    # --- deals ----------------------------------------------------------------
    op.create_table(
        "deals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pipeline_stage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("value_cents", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("probability", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", deal_close_reason_enum, nullable=True),
        sa.Column("msa_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_payment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("netsuite_internal_id", sa.String(length=50), nullable=True),
        sa.Column("netsuite_external_id", sa.String(length=100), nullable=True),
        sa.Column("netsuite_customer_id", sa.String(length=50), nullable=True),
        sa.Column("netsuite_sales_order_id", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_deals_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="SET NULL",
            name="fk_deals_contact_id",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"],
            ondelete="SET NULL",
            name="fk_deals_company_id",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"],
            ondelete="SET NULL",
            name="fk_deals_owner_id",
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_stage_id"], ["pipeline_stages.id"],
            ondelete="SET NULL",
            name="fk_deals_pipeline_stage_id",
        ),
    )
    op.create_index("ix_deals_workspace_id", "deals", ["workspace_id"])
    op.create_index("ix_deals_contact_id", "deals", ["contact_id"])
    op.create_index("ix_deals_company_id", "deals", ["company_id"])
    op.create_index("ix_deals_owner_id", "deals", ["owner_id"])
    op.create_index("ix_deals_pipeline_stage_id", "deals", ["pipeline_stage_id"])
    op.create_index("ix_deals_closed_at", "deals", ["closed_at"])

    # --- leads ----------------------------------------------------------------
    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", lead_status_enum, nullable=False, server_default="new"),
        sa.Column("score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("score_rationale", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_leads_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="CASCADE",
            name="fk_leads_contact_id",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"],
            ondelete="SET NULL",
            name="fk_leads_owner_id",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.id"],
            ondelete="SET NULL",
            name="fk_leads_deal_id",
        ),
    )
    op.create_index("ix_leads_workspace_id", "leads", ["workspace_id"])
    op.create_index("ix_leads_contact_id", "leads", ["contact_id"])
    op.create_index("ix_leads_owner_id", "leads", ["owner_id"])
    op.create_index("ix_leads_status", "leads", ["status"])

    # --- activities -----------------------------------------------------------
    op.create_table(
        "activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", activity_type_enum, nullable=False),
        sa.Column(
            "actor_type", activity_actor_type_enum,
            nullable=False, server_default="human",
        ),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_activities_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="CASCADE",
            name="fk_activities_contact_id",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.id"],
            ondelete="CASCADE",
            name="fk_activities_deal_id",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"],
            ondelete="CASCADE",
            name="fk_activities_lead_id",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"],
            ondelete="SET NULL",
            name="fk_activities_actor_id",
        ),
    )
    op.create_index("ix_activities_workspace_id", "activities", ["workspace_id"])
    op.create_index("ix_activities_contact_id", "activities", ["contact_id"])
    op.create_index("ix_activities_deal_id", "activities", ["deal_id"])
    op.create_index("ix_activities_type", "activities", ["type"])
    op.create_index("ix_activities_occurred_at", "activities", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_activities_occurred_at", table_name="activities")
    op.drop_index("ix_activities_type", table_name="activities")
    op.drop_index("ix_activities_deal_id", table_name="activities")
    op.drop_index("ix_activities_contact_id", table_name="activities")
    op.drop_index("ix_activities_workspace_id", table_name="activities")
    op.drop_table("activities")

    op.drop_index("ix_leads_status", table_name="leads")
    op.drop_index("ix_leads_owner_id", table_name="leads")
    op.drop_index("ix_leads_contact_id", table_name="leads")
    op.drop_index("ix_leads_workspace_id", table_name="leads")
    op.drop_table("leads")

    op.drop_index("ix_deals_closed_at", table_name="deals")
    op.drop_index("ix_deals_pipeline_stage_id", table_name="deals")
    op.drop_index("ix_deals_owner_id", table_name="deals")
    op.drop_index("ix_deals_company_id", table_name="deals")
    op.drop_index("ix_deals_contact_id", table_name="deals")
    op.drop_index("ix_deals_workspace_id", table_name="deals")
    op.drop_table("deals")

    op.drop_index("ix_contacts_source", table_name="contacts")
    op.drop_index("ix_contacts_lead_score", table_name="contacts")
    op.drop_index("ix_contacts_owner_id", table_name="contacts")
    op.drop_index("ix_contacts_company_id", table_name="contacts")
    op.drop_index("ix_contacts_workspace_id", table_name="contacts")
    op.drop_table("contacts")

    op.drop_index("ix_pipeline_stages_workspace_id", table_name="pipeline_stages")
    op.drop_table("pipeline_stages")

    op.drop_index("uq_companies_workspace_domain", table_name="companies")
    op.drop_index("ix_companies_workspace_id", table_name="companies")
    op.drop_table("companies")

    bind = op.get_bind()
    activity_actor_type_enum.drop(bind, checkfirst=True)
    activity_type_enum.drop(bind, checkfirst=True)
    deal_close_reason_enum.drop(bind, checkfirst=True)
    lead_status_enum.drop(bind, checkfirst=True)
    email_status_enum.drop(bind, checkfirst=True)
