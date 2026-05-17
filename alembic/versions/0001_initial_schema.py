"""Initial schema: workspaces, users, netsuite_sync_log.

Revision ID: 0001
Revises:
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(*values: str, name: str) -> postgresql.ENUM:
    """ENUM declared with `create_type=False` so the type is only created via
    the explicit `.create(bind, checkfirst=True)` call below — preventing
    SQLAlchemy from emitting a second CREATE TYPE during CREATE TABLE.
    """
    return postgresql.ENUM(*values, name=name, create_type=False)


user_role_enum = _enum("admin", "manager", "rep", "readonly", name="user_role")
sync_direction_enum = _enum(
    "apex_to_netsuite", "netsuite_to_apex", "bidirectional",
    name="sync_direction",
)
sync_status_enum = _enum(
    "pending", "synced", "failed", "conflict",
    name="sync_status",
)


def upgrade() -> None:
    # --- workspaces -----------------------------------------------------------
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("netsuite_account_id", sa.String(length=50), nullable=True),
        sa.Column("netsuite_consumer_key", sa.String(length=500), nullable=True),
        sa.Column("netsuite_consumer_secret", sa.String(length=500), nullable=True),
        sa.Column("netsuite_token_id", sa.String(length=500), nullable=True),
        sa.Column("netsuite_token_secret", sa.String(length=500), nullable=True),
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
    )
    # Unique-index on slug doubles as the uniqueness constraint to match
    # `slug: Mapped[str] = mapped_column(..., unique=True, index=True)` in the
    # Workspace model — keeping a separate UniqueConstraint here would cause
    # `alembic check` to report a phantom drift.
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)

    # --- users ----------------------------------------------------------------
    user_role_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=500), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("role", user_role_enum, nullable=False, server_default="rep"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_users_workspace_id",
        ),
    )
    op.create_index("ix_users_workspace_id", "users", ["workspace_id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # --- netsuite_sync_log ----------------------------------------------------
    sync_direction_enum.create(op.get_bind(), checkfirst=True)
    sync_status_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "netsuite_sync_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("apex_entity_type", sa.String(length=50), nullable=False),
        sa.Column("apex_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("netsuite_record_type", sa.String(length=50), nullable=False),
        sa.Column("netsuite_internal_id", sa.String(length=50), nullable=True),
        sa.Column("netsuite_external_id", sa.String(length=100), nullable=True),
        sa.Column("sync_direction", sync_direction_enum, nullable=False),
        sa.Column("status", sync_status_enum, nullable=False, server_default="pending"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("apex_checksum", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            ondelete="CASCADE",
            name="fk_netsuite_sync_log_workspace_id",
        ),
    )
    op.create_index(
        "ix_netsuite_sync_log_entity",
        "netsuite_sync_log",
        ["workspace_id", "apex_entity_type", "apex_entity_id"],
    )
    op.create_index(
        "ix_netsuite_sync_log_status",
        "netsuite_sync_log",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_netsuite_sync_log_status", table_name="netsuite_sync_log")
    op.drop_index("ix_netsuite_sync_log_entity", table_name="netsuite_sync_log")
    op.drop_table("netsuite_sync_log")
    sync_status_enum.drop(op.get_bind(), checkfirst=True)
    sync_direction_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_workspace_id", table_name="users")
    op.drop_table("users")
    user_role_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_workspaces_slug", table_name="workspaces")
    op.drop_table("workspaces")
