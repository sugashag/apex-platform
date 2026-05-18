"""SMS — send outbound, list inbound/outbound."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.config import settings
from app.dependencies import CurrentUser, DbSession
from app.models.activity import Activity, ActivityType, ActorType
from app.models.contact import Contact
from app.models.sms_message import SmsDirection, SmsMessage, SmsStatus
from app.schemas.sms_message import (
    SmsMessageCreate,
    SmsMessageListResponse,
    SmsMessageResponse,
)
from app.services.twilio_service import twilio_service
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/sms", tags=["sms"])


@router.post(
    "", response_model=SmsMessageResponse, status_code=status.HTTP_201_CREATED
)
async def send_sms(
    payload: SmsMessageCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> SmsMessageResponse:
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

    from_number = payload.from_number or settings.TWILIO_FROM_NUMBER
    if from_number is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_number is required (or set TWILIO_FROM_NUMBER)",
        )

    twilio_sid = await twilio_service.send_sms(
        to_number=payload.to_number,
        from_number=from_number,
        body=payload.body,
    )

    now = datetime.now(UTC)
    sms = SmsMessage(
        workspace_id=current_user.workspace_id,
        contact_id=payload.contact_id,
        twilio_message_sid=twilio_sid,
        direction=SmsDirection.OUTBOUND,
        from_number=from_number,
        to_number=payload.to_number,
        body=payload.body,
        status=SmsStatus.SENT,
        sent_at=now,
    )
    db.add(sms)

    if payload.contact_id is not None:
        db.add(
            Activity(
                workspace_id=current_user.workspace_id,
                contact_id=payload.contact_id,
                actor_id=current_user.id,
                type=ActivityType.SMS,
                actor_type=ActorType.HUMAN,
                subject=f"SMS to {payload.to_number}",
                body=payload.body,
                occurred_at=now,
            )
        )

    await db.commit()
    await db.refresh(sms)
    return SmsMessageResponse.model_validate(sms)


@router.get("", response_model=SmsMessageListResponse)
async def list_sms(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    contact_id: UUID | None = None,
    direction: SmsDirection | None = None,
) -> PaginatedResponse[SmsMessageResponse]:
    stmt = select(SmsMessage).where(
        SmsMessage.workspace_id == current_user.workspace_id
    )
    if contact_id is not None:
        stmt = stmt.where(SmsMessage.contact_id == contact_id)
    if direction is not None:
        stmt = stmt.where(SmsMessage.direction == direction)

    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(SmsMessage.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    items = [SmsMessageResponse.model_validate(m) for m in result.scalars().all()]
    return PaginatedResponse.build(items=items, total=total, params=pagination)
