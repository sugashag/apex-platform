"""Attribution: tracking_token, visitor_sessions, page_views, attributions, form_submissions.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(*values: str, name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


attribution_touch_type_enum = _enum(
    "first_touch", "last_touch", "assisted",
    name="attribution_touch_type",
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

    # --- tracking_token on workspaces ----------------------------------------
    op.add_column(
        "workspaces",
        sa.Column("tracking_token", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_workspaces_tracking_token", "workspaces", ["tracking_token"]
    )

    # --- enums ---------------------------------------------------------------
    attribution_touch_type_enum.create(bind, checkfirst=True)

    # --- visitor_sessions ----------------------------------------------------
    op.create_table(
        "visitor_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("campaign", sa.String(length=255), nullable=True),
        sa.Column("medium", sa.String(length=100), nullable=True),
        sa.Column("content", sa.String(length=255), nullable=True),
        sa.Column("term", sa.String(length=255), nullable=True),
        sa.Column("landing_page_url", sa.String(length=2000), nullable=True),
        sa.Column("referrer_url", sa.String(length=2000), nullable=True),
        sa.Column("gclid", sa.String(length=255), nullable=True),
        sa.Column("fbclid", sa.String(length=255), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="1"),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_visitor_sessions_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="SET NULL",
            name="fk_visitor_sessions_contact_id",
        ),
        sa.UniqueConstraint(
            "workspace_id", "session_id",
            name="uq_visitor_sessions_workspace_session",
        ),
    )
    op.create_index(
        "ix_visitor_sessions_workspace_id", "visitor_sessions", ["workspace_id"]
    )
    op.create_index(
        "ix_visitor_sessions_contact_id", "visitor_sessions", ["contact_id"]
    )
    op.create_index(
        "ix_visitor_sessions_session_id", "visitor_sessions", ["session_id"]
    )

    # --- page_views ----------------------------------------------------------
    op.create_table(
        "page_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("referrer", sa.String(length=2000), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("time_on_page_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_page_views_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["visitor_sessions.id"],
            ondelete="CASCADE",
            name="fk_page_views_session_id",
        ),
    )
    op.create_index("ix_page_views_workspace_id", "page_views", ["workspace_id"])
    op.create_index("ix_page_views_session_id", "page_views", ["session_id"])
    op.create_index("ix_page_views_occurred_at", "page_views", ["occurred_at"])

    # --- attributions --------------------------------------------------------
    op.create_table(
        "attributions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("touch_type", attribution_touch_type_enum, nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("campaign", sa.String(length=255), nullable=True),
        sa.Column("medium", sa.String(length=100), nullable=True),
        sa.Column("content", sa.String(length=255), nullable=True),
        sa.Column("term", sa.String(length=255), nullable=True),
        sa.Column("landing_page_url", sa.String(length=2000), nullable=True),
        sa.Column("referrer_url", sa.String(length=2000), nullable=True),
        sa.Column("gclid", sa.String(length=255), nullable=True),
        sa.Column("fbclid", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_attributions_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="CASCADE",
            name="fk_attributions_contact_id",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.id"],
            ondelete="SET NULL",
            name="fk_attributions_deal_id",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["visitor_sessions.id"],
            ondelete="SET NULL",
            name="fk_attributions_session_id",
        ),
    )
    op.create_index("ix_attributions_workspace_id", "attributions", ["workspace_id"])
    op.create_index("ix_attributions_contact_id", "attributions", ["contact_id"])
    op.create_index("ix_attributions_deal_id", "attributions", ["deal_id"])
    op.create_index("ix_attributions_touch_type", "attributions", ["touch_type"])
    op.create_index("ix_attributions_source", "attributions", ["source"])
    op.create_index("ix_attributions_occurred_at", "attributions", ["occurred_at"])

    # --- form_submissions ----------------------------------------------------
    op.create_table(
        "form_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("form_id", sa.String(length=100), nullable=False),
        sa.Column(
            "form_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("page_url", sa.String(length=2000), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_cols(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_form_submissions_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"],
            ondelete="SET NULL",
            name="fk_form_submissions_contact_id",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["visitor_sessions.id"],
            ondelete="SET NULL",
            name="fk_form_submissions_session_id",
        ),
    )
    op.create_index(
        "ix_form_submissions_workspace_id", "form_submissions", ["workspace_id"]
    )
    op.create_index(
        "ix_form_submissions_contact_id", "form_submissions", ["contact_id"]
    )
    op.create_index(
        "ix_form_submissions_form_id", "form_submissions", ["form_id"]
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_form_submissions_form_id", table_name="form_submissions")
    op.drop_index("ix_form_submissions_contact_id", table_name="form_submissions")
    op.drop_index("ix_form_submissions_workspace_id", table_name="form_submissions")
    op.drop_table("form_submissions")

    op.drop_index("ix_attributions_occurred_at", table_name="attributions")
    op.drop_index("ix_attributions_source", table_name="attributions")
    op.drop_index("ix_attributions_touch_type", table_name="attributions")
    op.drop_index("ix_attributions_deal_id", table_name="attributions")
    op.drop_index("ix_attributions_contact_id", table_name="attributions")
    op.drop_index("ix_attributions_workspace_id", table_name="attributions")
    op.drop_table("attributions")

    op.drop_index("ix_page_views_occurred_at", table_name="page_views")
    op.drop_index("ix_page_views_session_id", table_name="page_views")
    op.drop_index("ix_page_views_workspace_id", table_name="page_views")
    op.drop_table("page_views")

    op.drop_index("ix_visitor_sessions_session_id", table_name="visitor_sessions")
    op.drop_index("ix_visitor_sessions_contact_id", table_name="visitor_sessions")
    op.drop_index("ix_visitor_sessions_workspace_id", table_name="visitor_sessions")
    op.drop_table("visitor_sessions")

    attribution_touch_type_enum.drop(bind, checkfirst=True)

    op.drop_constraint(
        "uq_workspaces_tracking_token", "workspaces", type_="unique"
    )
    op.drop_column("workspaces", "tracking_token")
