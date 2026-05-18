"""Sequence model — a multi-step outbound email/SMS cadence."""

from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Sequence(Base):
    """A named outbound cadence."""

    __tablename__ = "sequences"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    exit_on_reply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
