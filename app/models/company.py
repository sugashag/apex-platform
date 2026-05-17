"""Company model."""

from uuid import UUID

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Company(Base):
    """An organization. Domain-unique within a workspace when present."""

    __tablename__ = "companies"

    workspace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    annual_revenue_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    netsuite_internal_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    netsuite_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index(
            "uq_companies_workspace_domain",
            "workspace_id",
            "domain",
            unique=True,
            postgresql_where=text("domain IS NOT NULL"),
        ),
    )
