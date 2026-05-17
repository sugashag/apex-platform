"""Voice call lifecycle — outbound initiation, listing, status updates."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import CurrentUser, DbSession
from app.models.activity import Activity, ActivityType, ActorType
from app.models.call import Call, CallDirection, CallHandledBy, CallStatus
from app.models.contact import Contact
from app.models.deal import Deal
from app.schemas.call import (
    CallCreate,
    CallListResponse,
    CallResponse,
    CallTokenResponse,
    CallUpdate,
)
from app.services.twilio_service import twilio_service
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/calls", tags=["calls"])


async def _load_call(db: AsyncSession, call_id: UUID, workspace_id: UUID) -> Call:
    result = await db.execute(
        select(Call).where(Call.id == call_id, Call.workspace_id == workspace_id)
    )
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Call not found"
        )
    return call


@router.post(
    "", response_model=CallResponse, status_code=status.HTTP_201_CREATED
)
async def initiate_call(
    payload: CallCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> CallResponse:
    if payload.contact_id is not None:
        check = await db.execute(
            select(Contact.id).where(
                Contact.id == payload.contact_id,
                Contact.workspace_id == current_user.workspace_id,
            )
        )
        if check.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="contact_id must belong to the same workspace",
            )
    if payload.deal_id is not None:
        check = await db.execute(
            select(Deal.id).where(
                Deal.id == payload.deal_id,
                Deal.workspace_id == current_user.workspace_id,
            )
        )
        if check.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="deal_id must belong to the same workspace",
            )

    from_number = payload.from_number or settings.TWILIO_FROM_NUMBER
    if from_number is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_number is required (or set TWILIO_FROM_NUMBER)",
        )

    twilio_sid = await twilio_service.initiate_call(
        to_number=payload.to_number, from_number=from_number
    )

    call = Call(
        workspace_id=current_user.workspace_id,
        contact_id=payload.contact_id,
        deal_id=payload.deal_id,
        initiated_by_id=current_user.id,
        twilio_call_sid=twilio_sid,
        direction=CallDirection.OUTBOUND,
        status=CallStatus.INITIATED,
        from_number=from_number,
        to_number=payload.to_number,
        handled_by=CallHandledBy.HUMAN,
        started_at=datetime.now(UTC),
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return CallResponse.model_validate(call)


@router.get("", response_model=CallListResponse)
async def list_calls(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    contact_id: UUID | None = None,
    deal_id: UUID | None = None,
    direction: CallDirection | None = None,
    status_filter: Annotated[CallStatus | None, Query(alias="status")] = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
) -> PaginatedResponse[CallResponse]:
    stmt = select(Call).where(Call.workspace_id == current_user.workspace_id)
    if contact_id is not None:
        stmt = stmt.where(Call.contact_id == contact_id)
    if deal_id is not None:
        stmt = stmt.where(Call.deal_id == deal_id)
    if direction is not None:
        stmt = stmt.where(Call.direction == direction)
    if status_filter is not None:
        stmt = stmt.where(Call.status == status_filter)
    if started_after is not None:
        stmt = stmt.where(Call.started_at >= started_after)
    if started_before is not None:
        stmt = stmt.where(Call.started_at <= started_before)

    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(Call.started_at.desc().nullslast(), Call.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    items = [CallResponse.model_validate(c) for c in result.scalars().all()]
    return PaginatedResponse.build(items=items, total=total, params=pagination)


@router.get("/token", response_model=CallTokenResponse)
async def get_call_token(current_user: CurrentUser) -> CallTokenResponse:
    """Mint a short-lived Twilio Client capability token for the softphone."""
    identity = f"user-{current_user.id}"
    ttl = 3600
    token = twilio_service.generate_capability_token(identity=identity, ttl_seconds=ttl)
    return CallTokenResponse(token=token, identity=identity, expires_in_seconds=ttl)


@router.get("/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> CallResponse:
    call = await _load_call(db, call_id, current_user.workspace_id)
    return CallResponse.model_validate(call)


@router.patch("/{call_id}", response_model=CallResponse)
async def update_call(
    call_id: UUID,
    payload: CallUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> CallResponse:
    call = await _load_call(db, call_id, current_user.workspace_id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(call, key, value)
    await db.commit()
    await db.refresh(call)
    return CallResponse.model_validate(call)


@router.post("/{call_id}/complete", response_model=CallResponse)
async def complete_call(
    call_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> CallResponse:
    call = await _load_call(db, call_id, current_user.workspace_id)
    now = datetime.now(UTC)
    call.status = CallStatus.COMPLETED
    call.ended_at = now
    if call.duration_seconds is None and call.started_at is not None:
        call.duration_seconds = int((now - call.started_at).total_seconds())

    if call.contact_id is not None:
        duration_str = (
            f"{call.duration_seconds // 60:02d}:{call.duration_seconds % 60:02d}"
            if call.duration_seconds is not None
            else "0:00"
        )
        db.add(
            Activity(
                workspace_id=call.workspace_id,
                contact_id=call.contact_id,
                deal_id=call.deal_id,
                actor_id=current_user.id,
                type=ActivityType.CALL,
                actor_type=ActorType.HUMAN,
                subject=f"{call.direction.value} call ({duration_str})",
                body=call.transcript,
                occurred_at=now,
            )
        )
    await db.commit()
    await db.refresh(call)
    return CallResponse.model_validate(call)
