"""NetSuite sync audit trail."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyncDirection(str, enum.Enum):
    APEX_TO_NETSUITE = "apex_to_netsuite"
    NETSUITE_TO_APEX = "netsuite_to_apex"
    BIDIRECTIONAL = "bidirectional"


class SyncStatus(str, enum.Enum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    CONFLICT = "conflict"


class NetSuiteSyncLog(Base):
    """One row per sync attempt between an APEX entity and a NetSuite record."""

    __tablename__ = "netsuite_sync_log"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    apex_entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    apex_entity_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    netsuite_record_type: Mapped[str] = mapped_column(String(50), nullable=False)
    netsuite_internal_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    netsuite_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sync_direction: Mapped[SyncDirection] = mapped_column(
        SAEnum(SyncDirection, name="sync_direction"),
        nullable=False,
    )
    status: Mapped[SyncStatus] = mapped_column(
        SAEnum(SyncStatus, name="sync_status"),
        nullable=False,
        default=SyncStatus.PENDING,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    apex_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index(
            "ix_netsuite_sync_log_entity",
            "workspace_id",
            "apex_entity_type",
            "apex_entity_id",
        ),
        Index("ix_netsuite_sync_log_status", "status"),
    )
