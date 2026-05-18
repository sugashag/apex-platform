"""Per-workspace NetSuite connection configuration.

Mirrors the fields on Workspace but lives in its own table so we can store
test-status timestamps, default GL accounts, and other settings without
bloating the Workspace row. One config per workspace.
"""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class NetSuiteTestStatus(enum.StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class NetSuiteConfig(Base):
    """Dedicated NetSuite settings table — encrypted credentials at rest."""

    __tablename__ = "netsuite_configs"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    account_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # These columns hold ciphertext in production; the application layer is
    # responsible for the crypto. Marked Text so we don't accidentally
    # truncate envelope-encrypted blobs.
    consumer_key: Mapped[str] = mapped_column(Text, nullable=False)
    consumer_secret: Mapped[str] = mapped_column(Text, nullable=False)
    token_id: Mapped[str] = mapped_column(Text, nullable=False)
    token_secret: Mapped[str] = mapped_column(Text, nullable=False)

    subsidiary_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_ar_account_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_revenue_account_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_test_status: Mapped[NetSuiteTestStatus | None] = mapped_column(
        pg_enum(NetSuiteTestStatus, name="netsuite_test_status"),
        nullable=True,
    )
    last_test_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_netsuite_configs_workspace"),
    )
