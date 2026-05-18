"""OnboardingChecklist — tracks self-serve workspace activation progress."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

CHECKLIST_STEPS: tuple[str, ...] = (
    "invite_team_member",
    "connect_email",
    "connect_twilio",
    "import_contacts",
    "create_first_deal",
    "configure_pipeline",
    "set_up_workflow",
    "connect_netsuite",
    "install_tracking_snippet",
)


class OnboardingChecklist(Base):
    """One row per workspace tracking which activation steps are done."""

    __tablename__ = "onboarding_checklists"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    invite_team_member: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    connect_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    connect_twilio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    import_contacts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    create_first_deal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    configure_pipeline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    set_up_workflow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    connect_netsuite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    install_tracking_snippet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", name="uq_onboarding_checklists_workspace"
        ),
    )

    def all_steps_done(self) -> bool:
        return all(getattr(self, step) for step in CHECKLIST_STEPS)
