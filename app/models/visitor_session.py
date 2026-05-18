"""VisitorSession model — anonymous website visitor before identity is known."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VisitorSession(Base):
    """A browser session on the marketing site. Becomes linked to a Contact
    once the visitor submits a form or is otherwise identified.
    """

    __tablename__ = "visitor_sessions"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Captured at first sight of the session so we never lose attribution.
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    campaign: Mapped[str | None] = mapped_column(String(255), nullable=True)
    medium: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content: Mapped[str | None] = mapped_column(String(255), nullable=True)
    term: Mapped[str | None] = mapped_column(String(255), nullable=True)
    landing_page_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    referrer_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    gclid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fbclid: Mapped[str | None] = mapped_column(String(255), nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "session_id",
            name="uq_visitor_sessions_workspace_session",
        ),
        Index("ix_visitor_sessions_contact_id", "contact_id"),
        Index("ix_visitor_sessions_session_id", "session_id"),
    )
