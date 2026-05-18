"""Onboarding checklist schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OnboardingChecklistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    invite_team_member: bool
    connect_email: bool
    connect_twilio: bool
    import_contacts: bool
    create_first_deal: bool
    configure_pipeline: bool
    set_up_workflow: bool
    connect_netsuite: bool
    install_tracking_snippet: bool
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
