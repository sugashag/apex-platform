"""Deal CRUD routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.dependencies import CurrentUser, DbSession
from app.models.activity import Activity, ActivityType, ActorType
from app.models.company import Company
from app.models.contact import Contact
from app.models.deal import CloseReason, Deal
from app.models.pipeline_stage import PipelineStage
from app.schemas.activity import ActivityResponse
from app.schemas.company import CompanyResponse
from app.schemas.contact import ContactResponse
from app.schemas.deal import (
    DealCreate,
    DealDetailResponse,
    DealListResponse,
    DealResponse,
    DealUpdate,
)
from app.services import workflow_engine
from app.services.deals import change_stage
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/deals", tags=["deals"])


async def _resolve_stage(
    db: DbSession,
    stage_id: UUID,
    workspace_id: UUID,
) -> PipelineStage:
    result = await db.execute(
        select(PipelineStage).where(
            PipelineStage.id == stage_id,
            PipelineStage.workspace_id == workspace_id,
        )
    )
    stage = result.scalar_one_or_none()
    if stage is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pipeline_stage_id is not in this workspace",
        )
    return stage


@router.post("", response_model=DealResponse, status_code=status.HTTP_201_CREATED)
async def create_deal(
    payload: DealCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> DealResponse:
    stage: PipelineStage | None = None
    if payload.pipeline_stage_id is not None:
        stage = await _resolve_stage(
            db, payload.pipeline_stage_id, current_user.workspace_id,
        )

    deal = Deal(
        workspace_id=current_user.workspace_id,
        contact_id=payload.contact_id,
        company_id=payload.company_id,
        owner_id=payload.owner_id,
        pipeline_stage_id=stage.id if stage else None,
        name=payload.name,
        value_cents=payload.value_cents,
        currency=payload.currency,
        probability=stage.probability_default if stage else payload.probability,
        expected_close_date=payload.expected_close_date,
    )
    db.add(deal)
    await db.flush()

    if stage is not None:
        activity = Activity(
            workspace_id=deal.workspace_id,
            deal_id=deal.id,
            contact_id=deal.contact_id,
            actor_id=current_user.id,
            actor_type=ActorType.HUMAN,
            type=ActivityType.STAGE_CHANGE,
            subject=f"Deal created at {stage.name}",
            meta={
                "from_stage_id": None,
                "to_stage_id": str(stage.id),
                "to_stage_name": stage.name,
                "probability": stage.probability_default,
            },
        )
        db.add(activity)

    await workflow_engine.trigger_workflow(
        db,
        workspace_id=deal.workspace_id,
        trigger_type="deal_created",
        entity_type="deal",
        entity_id=deal.id,
        context={
            "deal_id": str(deal.id),
            "contact_id": str(deal.contact_id) if deal.contact_id else None,
            "deal": {
                "id": str(deal.id),
                "name": deal.name,
                "value_cents": deal.value_cents,
                "currency": deal.currency,
                "stage_id": str(stage.id) if stage else None,
            },
        },
    )

    await db.commit()
    await db.refresh(deal)
    return DealResponse.model_validate(deal)


@router.get("", response_model=DealListResponse)
async def list_deals(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    owner_id: UUID | None = None,
    pipeline_stage_id: UUID | None = None,
    company_id: UUID | None = None,
    contact_id: UUID | None = None,
    close_reason: CloseReason | None = None,
    expected_close_from: Annotated[
        date | None, Query(description="Filter expected_close_date >= this.")
    ] = None,
    expected_close_to: Annotated[
        date | None, Query(description="Filter expected_close_date <= this.")
    ] = None,
    include_inactive: bool = False,
) -> PaginatedResponse[DealResponse]:
    stmt = select(Deal).where(Deal.workspace_id == current_user.workspace_id)

    if not include_inactive:
        stmt = stmt.where(Deal.is_active.is_(True))
    if owner_id is not None:
        stmt = stmt.where(Deal.owner_id == owner_id)
    if pipeline_stage_id is not None:
        stmt = stmt.where(Deal.pipeline_stage_id == pipeline_stage_id)
    if company_id is not None:
        stmt = stmt.where(Deal.company_id == company_id)
    if contact_id is not None:
        stmt = stmt.where(Deal.contact_id == contact_id)
    if close_reason is not None:
        stmt = stmt.where(Deal.close_reason == close_reason)
    if expected_close_from is not None:
        stmt = stmt.where(Deal.expected_close_date >= expected_close_from)
    if expected_close_to is not None:
        stmt = stmt.where(Deal.expected_close_date <= expected_close_to)

    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(Deal.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    rows = [DealResponse.model_validate(d) for d in result.scalars().all()]
    return PaginatedResponse.build(items=rows, total=total, params=pagination)


async def _load_deal(db: DbSession, deal_id: UUID, workspace_id: UUID) -> Deal:
    result = await db.execute(
        select(Deal).where(
            Deal.id == deal_id,
            Deal.workspace_id == workspace_id,
        )
    )
    deal = result.scalar_one_or_none()
    if deal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
    return deal


@router.get("/{deal_id}", response_model=DealDetailResponse)
async def get_deal(
    deal_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> DealDetailResponse:
    deal = await _load_deal(db, deal_id, current_user.workspace_id)

    contact: Contact | None = None
    if deal.contact_id is not None:
        contact_result = await db.execute(
            select(Contact).where(Contact.id == deal.contact_id)
        )
        contact = contact_result.scalar_one_or_none()

    company: Company | None = None
    if deal.company_id is not None:
        company_result = await db.execute(
            select(Company).where(Company.id == deal.company_id)
        )
        company = company_result.scalar_one_or_none()

    activities_result = await db.execute(
        select(Activity)
        .where(
            Activity.workspace_id == current_user.workspace_id,
            Activity.deal_id == deal_id,
        )
        .order_by(Activity.occurred_at.desc())
        .limit(20)
    )
    recent = [ActivityResponse.model_validate(a) for a in activities_result.scalars().all()]

    return DealDetailResponse(
        **DealResponse.model_validate(deal).model_dump(),
        contact=ContactResponse.model_validate(contact) if contact else None,
        company=CompanyResponse.model_validate(company) if company else None,
        recent_activities=recent,
    )


@router.patch("/{deal_id}", response_model=DealResponse)
async def update_deal(
    deal_id: UUID,
    payload: DealUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> DealResponse:
    deal = await _load_deal(db, deal_id, current_user.workspace_id)

    data = payload.model_dump(exclude_unset=True)
    new_stage_id = data.pop("pipeline_stage_id", "unset")
    stage_change_required = (
        new_stage_id != "unset" and new_stage_id != deal.pipeline_stage_id
    )

    for key, value in data.items():
        setattr(deal, key, value)

    if stage_change_required:
        if new_stage_id is None:
            deal.pipeline_stage_id = None
        else:
            new_stage = await _resolve_stage(
                db, new_stage_id, current_user.workspace_id,
            )
            await change_stage(
                db,
                deal=deal,
                new_stage=new_stage,
                actor_id=current_user.id,
                actor_type=ActorType.HUMAN,
            )

    await db.commit()
    await db.refresh(deal)
    return DealResponse.model_validate(deal)


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal(
    deal_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    deal = await _load_deal(db, deal_id, current_user.workspace_id)
    deal.is_active = False
    await db.commit()
