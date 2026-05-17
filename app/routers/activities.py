"""Activity routes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.dependencies import CurrentUser, DbSession
from app.models.activity import Activity, ActivityType, ActorType
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.lead import Lead
from app.schemas.activity import ActivityCreate, ActivityListResponse, ActivityResponse
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/activities", tags=["activities"])


async def _assert_in_workspace(
    db: DbSession,
    model: type,
    entity_id: UUID,
    workspace_id: UUID,
    label: str,
) -> None:
    result = await db.execute(
        select(model.id).where(  # type: ignore[attr-defined]
            model.id == entity_id,  # type: ignore[attr-defined]
            model.workspace_id == workspace_id,  # type: ignore[attr-defined]
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} is not in this workspace",
        )


@router.post("", response_model=ActivityResponse, status_code=status.HTTP_201_CREATED)
async def create_activity(
    payload: ActivityCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> ActivityResponse:
    if payload.contact_id is None and payload.deal_id is None and payload.lead_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of contact_id, deal_id, lead_id must be supplied",
        )
    ws_id = current_user.workspace_id
    if payload.contact_id is not None:
        await _assert_in_workspace(db, Contact, payload.contact_id, ws_id, "contact_id")
    if payload.deal_id is not None:
        await _assert_in_workspace(db, Deal, payload.deal_id, ws_id, "deal_id")
    if payload.lead_id is not None:
        await _assert_in_workspace(db, Lead, payload.lead_id, ws_id, "lead_id")

    activity = Activity(
        workspace_id=current_user.workspace_id,
        actor_id=current_user.id,
        actor_type=payload.actor_type,
        type=payload.type,
        contact_id=payload.contact_id,
        deal_id=payload.deal_id,
        lead_id=payload.lead_id,
        subject=payload.subject,
        body=payload.body,
        meta=payload.meta,
        occurred_at=payload.occurred_at,
    )
    db.add(activity)
    await db.commit()
    await db.refresh(activity)
    return ActivityResponse.model_validate(activity)


@router.get("", response_model=ActivityListResponse)
async def list_activities(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    contact_id: UUID | None = None,
    deal_id: UUID | None = None,
    lead_id: UUID | None = None,
    type: ActivityType | None = None,  # noqa: A002
    actor_type: ActorType | None = None,
    occurred_from: Annotated[datetime | None, Query(description="occurred_at >= this.")] = None,
    occurred_to: Annotated[datetime | None, Query(description="occurred_at <= this.")] = None,
) -> PaginatedResponse[ActivityResponse]:
    stmt = select(Activity).where(Activity.workspace_id == current_user.workspace_id)
    if contact_id is not None:
        stmt = stmt.where(Activity.contact_id == contact_id)
    if deal_id is not None:
        stmt = stmt.where(Activity.deal_id == deal_id)
    if lead_id is not None:
        stmt = stmt.where(Activity.lead_id == lead_id)
    if type is not None:
        stmt = stmt.where(Activity.type == type)
    if actor_type is not None:
        stmt = stmt.where(Activity.actor_type == actor_type)
    if occurred_from is not None:
        stmt = stmt.where(Activity.occurred_at >= occurred_from)
    if occurred_to is not None:
        stmt = stmt.where(Activity.occurred_at <= occurred_to)

    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(Activity.occurred_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    rows = [ActivityResponse.model_validate(a) for a in result.scalars().all()]
    return PaginatedResponse.build(items=rows, total=total, params=pagination)
