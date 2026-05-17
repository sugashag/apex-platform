"""Pipeline-stage routes."""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import CurrentUser, DbSession
from app.models.pipeline_stage import PipelineStage
from app.schemas.pipeline_stage import (
    PipelineStageCreate,
    PipelineStageReorderRequest,
    PipelineStageResponse,
    PipelineStageUpdate,
)

router = APIRouter(prefix="/pipeline-stages", tags=["pipeline-stages"])


@router.get("", response_model=list[PipelineStageResponse])
async def list_stages(
    db: DbSession,
    current_user: CurrentUser,
) -> list[PipelineStageResponse]:
    result = await db.execute(
        select(PipelineStage)
        .where(PipelineStage.workspace_id == current_user.workspace_id)
        .order_by(PipelineStage.position)
    )
    return [PipelineStageResponse.model_validate(s) for s in result.scalars().all()]


@router.post("", response_model=PipelineStageResponse, status_code=status.HTTP_201_CREATED)
async def create_stage(
    payload: PipelineStageCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> PipelineStageResponse:
    stage = PipelineStage(
        workspace_id=current_user.workspace_id,
        **payload.model_dump(),
    )
    db.add(stage)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A stage with this position already exists",
        ) from exc
    await db.refresh(stage)
    return PipelineStageResponse.model_validate(stage)


@router.patch("/{stage_id}", response_model=PipelineStageResponse)
async def update_stage(
    stage_id: UUID,
    payload: PipelineStageUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> PipelineStageResponse:
    result = await db.execute(
        select(PipelineStage).where(
            PipelineStage.id == stage_id,
            PipelineStage.workspace_id == current_user.workspace_id,
        )
    )
    stage = result.scalar_one_or_none()
    if stage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(stage, key, value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A stage with this position already exists",
        ) from exc
    await db.refresh(stage)
    return PipelineStageResponse.model_validate(stage)


@router.put("/reorder", response_model=list[PipelineStageResponse])
async def reorder_stages(
    payload: PipelineStageReorderRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> list[PipelineStageResponse]:
    """Atomically reposition stages.

    To dodge the `(workspace_id, position)` unique constraint we first move every
    affected stage to a unique negative position, then apply the requested
    positions.
    """
    ids = [item.id for item in payload.stages]
    result = await db.execute(
        select(PipelineStage).where(
            PipelineStage.workspace_id == current_user.workspace_id,
            PipelineStage.id.in_(ids),
        )
    )
    stages = {s.id: s for s in result.scalars().all()}
    if len(stages) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more stages were not found in this workspace",
        )
    positions = [item.position for item in payload.stages]
    if len(set(positions)) != len(positions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reorder positions must be unique",
        )

    # Two-phase update so unique (workspace_id, position) never collides mid-flight.
    sentinel_base = -(abs(hash(uuid4())) % 1_000_000_000) - 1
    for offset, stage_id in enumerate(ids):
        stages[stage_id].position = sentinel_base - offset
    await db.flush()

    for item in payload.stages:
        stages[item.id].position = item.position

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reorder conflicts with existing stage positions",
        ) from exc

    refreshed = await db.execute(
        select(PipelineStage)
        .where(PipelineStage.workspace_id == current_user.workspace_id)
        .order_by(PipelineStage.position)
    )
    return [PipelineStageResponse.model_validate(s) for s in refreshed.scalars().all()]
