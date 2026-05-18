"""FormSubmission model — captures marketing-site form submissions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FormSubmission(Base):
    __tablename__ = "form_submissions"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("visitor_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    form_id: Mapped[str] = mapped_column(String(100), nullable=False)
    form_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    page_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_form_submissions_contact_id", "contact_id"),
        Index("ix_form_submissions_form_id", "form_id"),
    )
