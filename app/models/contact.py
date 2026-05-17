"""Contact model — a person, scoped to a workspace, optionally linked to a company."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class EmailStatus(enum.StrEnum):
    ACTIVE = "active"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"


class Contact(Base):
    """A person tracked in CRM. Email is unique per workspace."""

    __tablename__ = "contacts"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    lead_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_campaign: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_medium: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_term: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_content: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    email_status: Mapped[EmailStatus] = mapped_column(
        pg_enum(EmailStatus, name="email_status"),
        nullable=False,
        default=EmailStatus.ACTIVE,
    )
    netsuite_internal_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    netsuite_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("workspace_id", "email", name="uq_contacts_workspace_email"),
        Index("ix_contacts_company_id", "company_id"),
        Index("ix_contacts_owner_id", "owner_id"),
        Index("ix_contacts_lead_score", "lead_score"),
        Index("ix_contacts_source", "source"),
    )
