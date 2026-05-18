"""Plan model — APEX subscription tiers."""

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Plan(Base):
    """A self-serve subscription tier offered to APEX customers."""

    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    price_cents_monthly: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents_annual: Mapped[int] = mapped_column(Integer, nullable=False)
    max_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_contacts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    includes_netsuite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    includes_ai_agents: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stripe_price_id_monthly: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_price_id_annual: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
