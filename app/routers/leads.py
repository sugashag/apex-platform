"""Lead CRUD and conversion routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.dependencies import CurrentUser, DbSession
from app.models.contact import Contact
from app.models.lead import Lead, LeadStatus
from app.schemas.contact import ContactResponse
from app.schemas.deal import DealResponse
from app.schemas.lead import (
    LeadConvertRequest,
    LeadCreate,
    LeadDetailResponse,
    LeadListResponse,
    LeadResponse,
    LeadUpdate,
)
from app.services.leads import after_lead_created, convert_to_deal
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/leads", tags=["leads"])


@router.post("", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> LeadResponse:
    contact_result = await db.execute(
        select(Contact).where(
            Contact.id == payload.contact_id,
            Contact.workspace_id == current_user.workspace_id,
        )
    )
    if contact_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="contact_id is not in this workspace",
        )

    lead = Lead(
        workspace_id=current_user.workspace_id,
        **payload.model_dump(),
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    await after_lead_created(lead)
    return LeadResponse.model_validate(lead)


@router.get("", response_model=LeadListResponse)
async def list_leads(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    status_filter: Annotated[
        LeadStatus | None,
        Query(alias="status", description="Filter by lead status."),
    ] = None,
    owner_id: UUID | None = None,
    source: str | None = None,
    score_min: Annotated[int | None, Query(ge=0)] = None,
    score_max: Annotated[int | None, Query(ge=0)] = None,
) -> PaginatedResponse[LeadResponse]:
    stmt = select(Lead).where(Lead.workspace_id == current_user.workspace_id)

    if status_filter is not None:
        stmt = stmt.where(Lead.status == status_filter)
    if owner_id is not None:
        stmt = stmt.where(Lead.owner_id == owner_id)
    if source is not None:
        stmt = stmt.where(Lead.source == source)
    if score_min is not None:
        stmt = stmt.where(Lead.score >= score_min)
    if score_max is not None:
        stmt = stmt.where(Lead.score <= score_max)

    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(Lead.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    rows = [LeadResponse.model_validate(lead) for lead in result.scalars().all()]
    return PaginatedResponse.build(items=rows, total=total, params=pagination)


async def _load_lead(db: DbSession, lead_id: UUID, workspace_id: UUID) -> Lead:
    result = await db.execute(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.workspace_id == workspace_id,
        )
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return lead


@router.get("/{lead_id}", response_model=LeadDetailResponse)
async def get_lead(
    lead_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> LeadDetailResponse:
    lead = await _load_lead(db, lead_id, current_user.workspace_id)

    contact_result = await db.execute(
        select(Contact).where(Contact.id == lead.contact_id)
    )
    contact = contact_result.scalar_one()
    return LeadDetailResponse(
        **LeadResponse.model_validate(lead).model_dump(),
        contact=ContactResponse.model_validate(contact),
    )


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> LeadResponse:
    lead = await _load_lead(db, lead_id, current_user.workspace_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(lead, key, value)
    await db.commit()
    await db.refresh(lead)
    return LeadResponse.model_validate(lead)


@router.post("/{lead_id}/convert", response_model=DealResponse, status_code=status.HTTP_201_CREATED)
async def convert_lead(
    lead_id: UUID,
    payload: LeadConvertRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> DealResponse:
    lead = await _load_lead(db, lead_id, current_user.workspace_id)
    if lead.status == LeadStatus.CONVERTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lead is already converted",
        )
    try:
        deal = await convert_to_deal(
            db,
            lead=lead,
            payload=payload,
            actor_id=current_user.id,
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    await db.commit()
    await db.refresh(deal)
    return DealResponse.model_validate(deal)
