"""Plan schemas — public plan catalog."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    price_cents_monthly: int
    price_cents_annual: int
    max_users: int | None
    max_contacts: int | None
    includes_netsuite: bool
    includes_ai_agents: bool
    is_active: bool
    is_public: bool
    created_at: datetime
    updated_at: datetime
