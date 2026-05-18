"""PageView model — individual page-view event within a visitor session.

We inherit from Base for the shared `id` + timestamp columns. PageView rows
are effectively append-only — `updated_at` is unused but inexpensive, and
keeping the inheritance consistent simplifies the rest of the ORM tooling.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PageView(Base):
    __tablename__ = "page_views"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("visitor_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    referrer: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    time_on_page_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_page_views_session_id", "session_id"),
        Index("ix_page_views_occurred_at", "occurred_at"),
    )
