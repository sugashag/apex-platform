"""Workspace model — the multi-tenant boundary for APEX."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Workspace(Base):
    """A tenant. Every domain row in APEX is scoped to exactly one workspace.

    NetSuite credentials live here because each workspace corresponds to
    a single NetSuite account. In production these fields are encrypted at rest.
    """

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    netsuite_account_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    netsuite_consumer_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    netsuite_consumer_secret: Mapped[str | None] = mapped_column(String(500), nullable=True)
    netsuite_token_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    netsuite_token_secret: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Public, read-only token used by the marketing-site JS snippet to identify
    # the workspace when posting attribution events. Safe to expose in browser
    # source — it grants only the tracking endpoints, never API access.
    tracking_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )

    users: Mapped[list["User"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
