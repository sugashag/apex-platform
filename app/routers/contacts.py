"""Contact CRUD + contact-timeline routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.dependencies import CurrentUser, DbSession
from app.middleware.plan_enforcement import check_contact_limit
from app.middleware.rbac import require_manager_or_above
from app.models.activity import Activity, ActivityType, ActorType
from app.models.contact import Contact, EmailStatus
from app.models.user import User
from app.schemas.activity import ActivityListResponse, ActivityResponse
from app.schemas.contact import (
    ContactCreate,
    ContactDetailResponse,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
)
from app.services import workflow_engine
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    payload: ContactCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> ContactResponse:
    await check_contact_limit(db, current_user.workspace_id)
    contact = Contact(
        workspace_id=current_user.workspace_id,
        **payload.model_dump(),
    )
    db.add(contact)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A contact with this email already exists in your workspace",
        ) from exc

    await workflow_engine.trigger_workflow(
        db,
        workspace_id=contact.workspace_id,
        trigger_type="contact_created",
        entity_type="contact",
        entity_id=contact.id,
        context={
            "contact_id": str(contact.id),
            "contact": {
                "id": str(contact.id),
                "email": contact.email,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "source": contact.source,
            },
        },
    )

    await db.commit()
    await db.refresh(contact)
    return ContactResponse.model_validate(contact)


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    company_id: UUID | None = None,
    owner_id: UUID | None = None,
    source: str | None = None,
    email_status: EmailStatus | None = None,
    lead_score_min: Annotated[int | None, Query(ge=0)] = None,
    lead_score_max: Annotated[int | None, Query(ge=0)] = None,
    search: Annotated[
        str | None,
        Query(description="Substring search across name, email."),
    ] = None,
    include_inactive: bool = False,
) -> PaginatedResponse[ContactResponse]:
    stmt = select(Contact).where(Contact.workspace_id == current_user.workspace_id)

    if not include_inactive:
        stmt = stmt.where(Contact.is_active.is_(True))
    if company_id is not None:
        stmt = stmt.where(Contact.company_id == company_id)
    if owner_id is not None:
        stmt = stmt.where(Contact.owner_id == owner_id)
    if source is not None:
        stmt = stmt.where(Contact.source == source)
    if email_status is not None:
        stmt = stmt.where(Contact.email_status == email_status)
    if lead_score_min is not None:
        stmt = stmt.where(Contact.lead_score >= lead_score_min)
    if lead_score_max is not None:
        stmt = stmt.where(Contact.lead_score <= lead_score_max)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Contact.email.ilike(like),
                Contact.first_name.ilike(like),
                Contact.last_name.ilike(like),
            )
        )

    count_result = await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(Contact.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    rows = [ContactResponse.model_validate(c) for c in result.scalars().all()]
    return PaginatedResponse.build(items=rows, total=total, params=pagination)


async def _load_contact(
    db: DbSession,
    contact_id: UUID,
    workspace_id: UUID,
) -> Contact:
    result = await db.execute(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.workspace_id == workspace_id,
        )
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


@router.get("/{contact_id}", response_model=ContactDetailResponse)
async def get_contact(
    contact_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> ContactDetailResponse:
    contact = await _load_contact(db, contact_id, current_user.workspace_id)

    activities_result = await db.execute(
        select(Activity)
        .where(
            Activity.workspace_id == current_user.workspace_id,
            Activity.contact_id == contact_id,
        )
        .order_by(Activity.occurred_at.desc())
        .limit(10)
    )
    recent = [ActivityResponse.model_validate(a) for a in activities_result.scalars().all()]

    return ContactDetailResponse(
        **ContactResponse.model_validate(contact).model_dump(),
        recent_activities=recent,
    )


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: UUID,
    payload: ContactUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> ContactResponse:
    contact = await _load_contact(db, contact_id, current_user.workspace_id)

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(contact, key, value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A contact with this email already exists in your workspace",
        ) from exc
    await db.refresh(contact)
    return ContactResponse.model_validate(contact)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_manager_or_above()),
) -> None:
    contact = await _load_contact(db, contact_id, current_user.workspace_id)
    contact.is_active = False
    await db.commit()


@router.get("/{contact_id}/timeline", response_model=ActivityListResponse)
async def contact_timeline(
    contact_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    type: ActivityType | None = None,  # noqa: A002 — `type` is the query param the spec asks for
    actor_type: ActorType | None = None,
) -> PaginatedResponse[ActivityResponse]:
    await _load_contact(db, contact_id, current_user.workspace_id)

    stmt = select(Activity).where(
        Activity.workspace_id == current_user.workspace_id,
        Activity.contact_id == contact_id,
    )
    if type is not None:
        stmt = stmt.where(Activity.type == type)
    if actor_type is not None:
        stmt = stmt.where(Activity.actor_type == actor_type)

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
