"""Payments, MSA documents, NetSuite per-workspace config.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(*values: str, name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


payment_status_enum = _enum(
    "pending", "succeeded", "failed", "refunded", "cancelled",
    name="payment_status",
)
msa_status_enum = _enum(
    "draft", "sent", "signed", "expired", "cancelled",
    name="msa_status",
)
netsuite_test_status_enum = _enum(
    "success", "failed",
    name="netsuite_test_status",
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
    payment_status_enum.create(bind, checkfirst=True)
    msa_status_enum.create(bind, checkfirst=True)
    netsuite_test_status_enum.create(bind, checkfirst=True)

    # --- payments -----------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stripe_payment_intent_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_invoice_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("status", payment_status_enum, nullable=False, server_default="pending"),
        sa.Column(
            "is_first_payment", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("netsuite_transaction_id", sa.String(length=50), nullable=True),
        sa.Column("netsuite_invoice_id", sa.String(length=50), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_payments_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.id"],
            ondelete="SET NULL",
            name="fk_payments_deal_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="SET NULL",
            name="fk_payments_contact_id",
        ),
        sa.UniqueConstraint(
            "stripe_payment_intent_id",
            name="uq_payments_stripe_payment_intent_id",
        ),
    )
    op.create_index("ix_payments_workspace_id", "payments", ["workspace_id"])
    op.create_index("ix_payments_deal_id", "payments", ["deal_id"])
    op.create_index("ix_payments_contact_id", "payments", ["contact_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index(
        "ix_payments_stripe_customer_id", "payments", ["stripe_customer_id"]
    )

    # --- msa_documents ------------------------------------------------------
    op.create_table(
        "msa_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", msa_status_enum, nullable=False, server_default="draft"),
        sa.Column("document_url", sa.String(length=1000), nullable=True),
        sa.Column("signing_url", sa.String(length=1000), nullable=True),
        sa.Column("external_envelope_id", sa.String(length=255), nullable=True),
        sa.Column("signer_email", sa.String(length=255), nullable=True),
        sa.Column("signer_name", sa.String(length=255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("netsuite_file_id", sa.String(length=50), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_msa_documents_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.id"],
            ondelete="CASCADE",
            name="fk_msa_documents_deal_id",
        ),
        sa.ForeignKeyConstraint(
            ["generated_by_id"], ["users.id"],
            ondelete="SET NULL",
            name="fk_msa_documents_generated_by_id",
        ),
    )
    op.create_index("ix_msa_documents_workspace_id", "msa_documents", ["workspace_id"])
    op.create_index("ix_msa_documents_deal_id", "msa_documents", ["deal_id"])
    op.create_index("ix_msa_documents_status", "msa_documents", ["status"])

    # --- netsuite_configs ---------------------------------------------------
    op.create_table(
        "netsuite_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.String(length=50), nullable=False),
        sa.Column("consumer_key", sa.Text(), nullable=False),
        sa.Column("consumer_secret", sa.Text(), nullable=False),
        sa.Column("token_id", sa.Text(), nullable=False),
        sa.Column("token_secret", sa.Text(), nullable=False),
        sa.Column("subsidiary_id", sa.String(length=50), nullable=True),
        sa.Column("default_ar_account_id", sa.String(length=50), nullable=True),
        sa.Column("default_revenue_account_id", sa.String(length=50), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", netsuite_test_status_enum, nullable=True),
        sa.Column("last_test_error", sa.Text(), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_netsuite_configs_workspace_id",
        ),
        sa.UniqueConstraint(
            "workspace_id", name="uq_netsuite_configs_workspace",
        ),
    )

    # --- netsuite_sync_log: add (workspace_id, status, created_at) index ----
    op.create_index(
        "ix_netsuite_sync_log_ws_status_created",
        "netsuite_sync_log",
        ["workspace_id", "status", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index(
        "ix_netsuite_sync_log_ws_status_created",
        table_name="netsuite_sync_log",
    )

    op.drop_table("netsuite_configs")

    op.drop_index("ix_msa_documents_status", table_name="msa_documents")
    op.drop_index("ix_msa_documents_deal_id", table_name="msa_documents")
    op.drop_index("ix_msa_documents_workspace_id", table_name="msa_documents")
    op.drop_table("msa_documents")

    op.drop_index("ix_payments_stripe_customer_id", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_contact_id", table_name="payments")
    op.drop_index("ix_payments_deal_id", table_name="payments")
    op.drop_index("ix_payments_workspace_id", table_name="payments")
    op.drop_table("payments")

    netsuite_test_status_enum.drop(bind, checkfirst=True)
    msa_status_enum.drop(bind, checkfirst=True)
    payment_status_enum.drop(bind, checkfirst=True)
