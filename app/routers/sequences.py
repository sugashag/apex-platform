"""Sequence CRUD + enrollment routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.dependencies import CurrentUser, DbSession
from app.models.contact import Contact
from app.models.sequence import Sequence
from app.models.sequence_enrollment import (
    SequenceEnrollment,
    SequenceEnrollmentStatus,
)
from app.models.sequence_step import SequenceStep
from app.schemas.sequence import (
    SequenceCreate,
    SequenceDetailResponse,
    SequenceEnrollmentResponse,
    SequenceEnrollRequest,
    SequenceListResponse,
    SequenceResponse,
    SequenceStepResponse,
    SequenceUpdate,
)
from app.services import sequence_service
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/sequences", tags=["sequences"])
enrollments_router = APIRouter(prefix="/sequences", tags=["sequences"])


async def _load_sequence(
    db: DbSession, sequence_id: UUID, workspace_id: UUID
) -> Sequence:
    result = await db.execute(
        select(Sequence).where(
            Sequence.id == sequence_id,
            Sequence.workspace_id == workspace_id,
        )
    )
    sequence = result.scalar_one_or_none()
    if sequence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sequence not found"
        )
    return sequence


async def _build_detail(
    db: DbSession, sequence: Sequence
) -> SequenceDetailResponse:
    steps_result = await db.execute(
        select(SequenceStep)
        .where(SequenceStep.sequence_id == sequence.id)
        .order_by(SequenceStep.position.asc())
    )
    count_result = await db.execute(
        select(func.count()).where(SequenceEnrollment.sequence_id == sequence.id)
    )
    return SequenceDetailResponse(
        **SequenceResponse.model_validate(sequence).model_dump(),
        steps=[SequenceStepResponse.model_validate(s) for s in steps_result.scalars().all()],
        enrollment_count=int(count_result.scalar_one()),
    )


@router.post(
    "", response_model=SequenceDetailResponse, status_code=status.HTTP_201_CREATED
)
async def create_sequence(
    payload: SequenceCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> SequenceDetailResponse:
    sequence = Sequence(
        workspace_id=current_user.workspace_id,
        name=payload.name,
        is_active=payload.is_active,
        exit_on_reply=payload.exit_on_reply,
    )
    db.add(sequence)
    await db.flush()
    for step in payload.steps:
        db.add(SequenceStep(sequence_id=sequence.id, **step.model_dump()))
    await db.commit()
    await db.refresh(sequence)
    return await _build_detail(db, sequence)


@router.get("", response_model=SequenceListResponse)
async def list_sequences(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
) -> PaginatedResponse[SequenceResponse]:
    stmt = select(Sequence).where(Sequence.workspace_id == current_user.workspace_id)
    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = int(count_result.scalar_one())
    stmt = (
        stmt.order_by(Sequence.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    items = [SequenceResponse.model_validate(s) for s in result.scalars().all()]
    return PaginatedResponse.build(items=items, total=total, params=pagination)


@router.get("/{sequence_id}", response_model=SequenceDetailResponse)
async def get_sequence(
    sequence_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> SequenceDetailResponse:
    sequence = await _load_sequence(db, sequence_id, current_user.workspace_id)
    return await _build_detail(db, sequence)


@router.patch("/{sequence_id}", response_model=SequenceDetailResponse)
async def update_sequence(
    sequence_id: UUID,
    payload: SequenceUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> SequenceDetailResponse:
    sequence = await _load_sequence(db, sequence_id, current_user.workspace_id)
    data = payload.model_dump(exclude_unset=True)
    new_steps = data.pop("steps", None)
    for key, value in data.items():
        setattr(sequence, key, value)
    if new_steps is not None:
        existing = await db.execute(
            select(SequenceStep).where(SequenceStep.sequence_id == sequence.id)
        )
        for old in existing.scalars().all():
            await db.delete(old)
        for step in new_steps:
            db.add(SequenceStep(sequence_id=sequence.id, **step))
    await db.commit()
    await db.refresh(sequence)
    return await _build_detail(db, sequence)


@router.post(
    "/{sequence_id}/enroll",
    response_model=list[SequenceEnrollmentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def enroll(
    sequence_id: UUID,
    payload: SequenceEnrollRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> list[SequenceEnrollmentResponse]:
    sequence = await _load_sequence(db, sequence_id, current_user.workspace_id)

    # Validate contacts belong to this workspace.
    contact_check = await db.execute(
        select(Contact.id).where(
            Contact.id.in_(payload.contact_ids),
            Contact.workspace_id == current_user.workspace_id,
        )
    )
    valid_ids = {row[0] for row in contact_check.all()}
    invalid = [cid for cid in payload.contact_ids if cid not in valid_ids]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"contacts not in workspace: {invalid}",
        )

    enrollments: list[SequenceEnrollment] = []
    for contact_id in payload.contact_ids:
        try:
            enrollment = await sequence_service.enroll_contact(
                db,
                workspace_id=current_user.workspace_id,
                sequence_id=sequence.id,
                contact_id=contact_id,
                deal_id=payload.deal_id,
                enrolled_by_id=current_user.id,
            )
            enrollments.append(enrollment)
        except ValueError:
            # Already enrolled — skip silently.
            continue

    await db.commit()
    for e in enrollments:
        await db.refresh(e)
    return [SequenceEnrollmentResponse.model_validate(e) for e in enrollments]


@router.get(
    "/{sequence_id}/enrollments",
    response_model=list[SequenceEnrollmentResponse],
)
async def list_enrollments(
    sequence_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    status_filter: SequenceEnrollmentStatus | None = None,
) -> list[SequenceEnrollmentResponse]:
    await _load_sequence(db, sequence_id, current_user.workspace_id)
    stmt = select(SequenceEnrollment).where(
        SequenceEnrollment.sequence_id == sequence_id,
        SequenceEnrollment.workspace_id == current_user.workspace_id,
    )
    if status_filter is not None:
        stmt = stmt.where(SequenceEnrollment.status == status_filter)
    stmt = stmt.order_by(SequenceEnrollment.created_at.desc())
    result = await db.execute(stmt)
    return [
        SequenceEnrollmentResponse.model_validate(e)
        for e in result.scalars().all()
    ]


@enrollments_router.post(
    "/enrollments/{enrollment_id}/exit",
    response_model=SequenceEnrollmentResponse,
)
async def exit_enrollment(
    enrollment_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> SequenceEnrollmentResponse:
    enrollment = await db.get(SequenceEnrollment, enrollment_id)
    if enrollment is None or enrollment.workspace_id != current_user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment not found"
        )
    result = await sequence_service.exit_enrollment(db, enrollment_id)
    await db.commit()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment not found"
        )
    await db.refresh(result)
    return SequenceEnrollmentResponse.model_validate(result)
