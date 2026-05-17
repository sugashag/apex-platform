"""Lead services — conversion into deals."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity, ActivityType, ActorType
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.lead import Lead, LeadStatus
from app.models.pipeline_stage import PipelineStage
from app.schemas.lead import LeadConvertRequest


async def convert_to_deal(
    db: AsyncSession,
    *,
    lead: Lead,
    payload: LeadConvertRequest,
    actor_id: UUID | None,
    actor_type: ActorType = ActorType.HUMAN,
) -> Deal:
    """Create a Deal from a Lead, link it back, mark the lead converted.

    Caller commits. Raises ValueError if the supplied pipeline_stage_id is
    not in the same workspace as the lead.
    """
    pipeline_stage: PipelineStage | None = None
    if payload.pipeline_stage_id is not None:
        result = await db.execute(
            select(PipelineStage).where(
                PipelineStage.id == payload.pipeline_stage_id,
                PipelineStage.workspace_id == lead.workspace_id,
            )
        )
        pipeline_stage = result.scalar_one_or_none()
        if pipeline_stage is None:
            raise ValueError("pipeline_stage_id is not in this workspace")

    # Inherit company from the lead's contact if not explicitly provided.
    company_id = payload.company_id
    if company_id is None:
        contact_result = await db.execute(
            select(Contact.company_id).where(Contact.id == lead.contact_id)
        )
        company_id = contact_result.scalar_one_or_none()

    deal = Deal(
        workspace_id=lead.workspace_id,
        contact_id=lead.contact_id,
        company_id=company_id,
        owner_id=payload.owner_id or lead.owner_id,
        pipeline_stage_id=pipeline_stage.id if pipeline_stage else None,
        name=payload.name,
        value_cents=payload.value_cents,
        currency=payload.currency,
        probability=(
            pipeline_stage.probability_default if pipeline_stage else payload.probability
        ),
        expected_close_date=payload.expected_close_date,
    )
    db.add(deal)
    await db.flush()

    lead.status = LeadStatus.CONVERTED
    lead.converted_at = datetime.now(tz=UTC)
    lead.deal_id = deal.id

    activity = Activity(
        workspace_id=lead.workspace_id,
        deal_id=deal.id,
        lead_id=lead.id,
        contact_id=lead.contact_id,
        actor_id=actor_id,
        actor_type=actor_type,
        type=ActivityType.STAGE_CHANGE,
        subject="Lead converted to deal",
        meta={
            "lead_id": str(lead.id),
            "deal_id": str(deal.id),
            "to_stage_id": str(pipeline_stage.id) if pipeline_stage else None,
            "to_stage_name": pipeline_stage.name if pipeline_stage else None,
        },
    )
    db.add(activity)
    await db.flush()
    return deal
