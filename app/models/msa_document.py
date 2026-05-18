"""MSA document — Master Services Agreement generated for a deal."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enum_helpers import pg_enum


class MsaStatus(enum.StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    SIGNED = "signed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class MsaDocument(Base):
    """A generated MSA PDF and its signing lifecycle."""

    __tablename__ = "msa_documents"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    deal_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("deals.id", ondelete="CASCADE"),
        nullable=False,
    )
    generated_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[MsaStatus] = mapped_column(
        pg_enum(MsaStatus, name="msa_status"),
        nullable=False,
        default=MsaStatus.DRAFT,
    )
    document_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    signing_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    external_envelope_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    netsuite_file_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_msa_documents_workspace_id", "workspace_id"),
        Index("ix_msa_documents_deal_id", "deal_id"),
        Index("ix_msa_documents_status", "status"),
    )
