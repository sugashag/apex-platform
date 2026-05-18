"""LeadScoreHistory — append-only log of lead score changes for trend analysis."""

from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LeadScoreHistory(Base):
    """One row per lead-scoring run — powers the score trend chart."""

    __tablename__ = "lead_score_history"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    lead_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    score_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_lead_score_history_workspace_lead_created",
            "workspace_id",
            "lead_id",
            "created_at",
        ),
    )
