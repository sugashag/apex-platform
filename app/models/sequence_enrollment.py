"""SequenceEnrollment model — tracks a contact's progress through a Sequence."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class SequenceEnrollmentStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    EXITED_REPLY = "exited_reply"
    EXITED_MANUAL = "exited_manual"
    PAUSED = "paused"


class SequenceEnrollment(Base):
    """A contact's progress through a Sequence."""

    __tablename__ = "sequence_enrollments"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sequences.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    deal_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("deals.id", ondelete="SET NULL"),
        nullable=True,
    )
    enrolled_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[SequenceEnrollmentStatus] = mapped_column(
        pg_enum(SequenceEnrollmentStatus, name="sequence_enrollment_status"),
        nullable=False,
        default=SequenceEnrollmentStatus.ACTIVE,
    )
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_step_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    exited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_sequence_enrollments_workspace_id", "workspace_id"),
        Index("ix_sequence_enrollments_sequence_id", "sequence_id"),
        Index("ix_sequence_enrollments_contact_id", "contact_id"),
        Index("ix_sequence_enrollments_status", "status"),
        Index("ix_sequence_enrollments_next_step_at", "next_step_at"),
        Index(
            "uq_sequence_enrollments_active",
            "sequence_id",
            "contact_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )
