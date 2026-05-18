"""Deal services — stage transitions and the activity audit trail."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity, ActivityType, ActorType
from app.models.deal import CloseReason, Deal
from app.models.pipeline_stage import PipelineStage
from app.services.attribution_service import link_deal_to_attributions

logger = logging.getLogger(__name__)


async def change_stage(
    db: AsyncSession,
    *,
    deal: Deal,
    new_stage: PipelineStage,
    actor_id: UUID | None,
    actor_type: ActorType = ActorType.HUMAN,
) -> Activity:
    """Move a deal to a new pipeline stage and record an Activity.

    If `new_stage.is_won` or `new_stage.is_lost`, also stamp `closed_at`
    and `close_reason` on the deal. Caller commits the transaction.
    """
    previous_stage_id = deal.pipeline_stage_id
    deal.pipeline_stage_id = new_stage.id
    deal.probability = new_stage.probability_default

    if new_stage.is_won:
        deal.closed_at = datetime.now(tz=UTC)
        deal.close_reason = CloseReason.WON
        if deal.contact_id is not None:
            try:
                await link_deal_to_attributions(
                    db,
                    workspace_id=deal.workspace_id,
                    contact_id=deal.contact_id,
                    deal_id=deal.id,
                )
            except Exception:  # noqa: BLE001
                # Backfill is best-effort — never block the won transition.
                logger.exception(
                    "attribution backfill failed for deal %s", deal.id
                )
    elif new_stage.is_lost:
        deal.closed_at = datetime.now(tz=UTC)
        deal.close_reason = CloseReason.LOST
    else:
        # Reopening a closed deal — clear the close fields.
        deal.closed_at = None
        deal.close_reason = None

    activity = Activity(
        workspace_id=deal.workspace_id,
        deal_id=deal.id,
        contact_id=deal.contact_id,
        actor_id=actor_id,
        actor_type=actor_type,
        type=ActivityType.STAGE_CHANGE,
        subject=f"Stage → {new_stage.name}",
        meta={
            "from_stage_id": str(previous_stage_id) if previous_stage_id else None,
            "to_stage_id": str(new_stage.id),
            "to_stage_name": new_stage.name,
            "probability": new_stage.probability_default,
        },
    )
    db.add(activity)
    await db.flush()
    return activity
