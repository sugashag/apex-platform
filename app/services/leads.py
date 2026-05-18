"""Lead services — creation hook + conversion into deals."""

import logging
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
from app.services import workflow_engine
from app.services.agent_queue import enqueue

logger = logging.getLogger(__name__)


async def after_lead_created(lead: Lead) -> None:
    """Enqueue the lead scorer for a freshly created lead.

    Best-effort: if Redis is unavailable the call is logged + swallowed so
    lead creation never blocks on the queue.
    """
    await enqueue(
        "run_lead_scorer",
        lead.workspace_id,
        lead.id,
        trigger="lead_created",
    )


async def fire_lead_created_workflows(db: AsyncSession, lead: Lead) -> None:
    """Run workflow triggers for lead creation. Caller commits."""
    await workflow_engine.trigger_workflow(
        db,
        workspace_id=lead.workspace_id,
        trigger_type="lead_created",
        entity_type="lead",
        entity_id=lead.id,
        context={
            "lead_id": str(lead.id),
            "contact_id": str(lead.contact_id),
            "lead": {
                "id": str(lead.id),
                "status": lead.status.value,
                "score": lead.score,
                "source": lead.source,
            },
        },
    )


async def fire_lead_status_changed_workflows(
    db: AsyncSession,
    lead: Lead,
    *,
    previous_status: LeadStatus,
) -> None:
    """Run workflow triggers when a lead status changes. Caller commits."""
    await workflow_engine.trigger_workflow(
        db,
        workspace_id=lead.workspace_id,
        trigger_type="lead_status_changed",
        entity_type="lead",
        entity_id=lead.id,
        context={
            "lead_id": str(lead.id),
            "contact_id": str(lead.contact_id),
            "lead": {
                "id": str(lead.id),
                "previous_status": previous_status.value,
                "status": lead.status.value,
                "score": lead.score,
            },
        },
    )


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
