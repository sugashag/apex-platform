"""Workflow CRUD + run inspection + manual trigger + step approval."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.dependencies import CurrentUser, DbSession
from app.models.workflow import Workflow
from app.models.workflow_condition import WorkflowCondition
from app.models.workflow_run import WorkflowRun, WorkflowRunStatus
from app.models.workflow_step import WorkflowStep
from app.models.workflow_step_run import WorkflowStepRun
from app.schemas.workflow import (
    WorkflowConditionResponse,
    WorkflowCreate,
    WorkflowDetailResponse,
    WorkflowListResponse,
    WorkflowManualTrigger,
    WorkflowResponse,
    WorkflowRunDetailResponse,
    WorkflowRunListResponse,
    WorkflowRunResponse,
    WorkflowStepResponse,
    WorkflowStepRunResponse,
    WorkflowUpdate,
)
from app.services import workflow_engine
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/workflows", tags=["workflows"])
runs_router = APIRouter(tags=["workflows"])


async def _load_workflow(
    db: DbSession, workflow_id: UUID, workspace_id: UUID
) -> Workflow:
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.workspace_id == workspace_id,
        )
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found"
        )
    return workflow


async def _load_conditions_and_steps(
    db: DbSession, workflow_id: UUID
) -> tuple[list[WorkflowCondition], list[WorkflowStep]]:
    conds_result = await db.execute(
        select(WorkflowCondition)
        .where(WorkflowCondition.workflow_id == workflow_id)
        .order_by(WorkflowCondition.position.asc())
    )
    steps_result = await db.execute(
        select(WorkflowStep)
        .where(WorkflowStep.workflow_id == workflow_id)
        .order_by(WorkflowStep.position.asc())
    )
    return list(conds_result.scalars().all()), list(steps_result.scalars().all())


async def _build_detail(
    db: DbSession, workflow: Workflow
) -> WorkflowDetailResponse:
    conditions, steps = await _load_conditions_and_steps(db, workflow.id)
    return WorkflowDetailResponse(
        **WorkflowResponse.model_validate(workflow).model_dump(),
        conditions=[WorkflowConditionResponse.model_validate(c) for c in conditions],
        steps=[WorkflowStepResponse.model_validate(s) for s in steps],
    )


@router.post(
    "", response_model=WorkflowDetailResponse, status_code=status.HTTP_201_CREATED
)
async def create_workflow(
    payload: WorkflowCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> WorkflowDetailResponse:
    workflow = Workflow(
        workspace_id=current_user.workspace_id,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
        trigger_type=payload.trigger_type,
        trigger_config=payload.trigger_config,
    )
    db.add(workflow)
    await db.flush()

    for cond in payload.conditions:
        db.add(
            WorkflowCondition(
                workflow_id=workflow.id,
                **cond.model_dump(),
            )
        )
    for step in payload.steps:
        db.add(
            WorkflowStep(
                workflow_id=workflow.id,
                **step.model_dump(),
            )
        )
    await db.commit()
    await db.refresh(workflow)
    return await _build_detail(db, workflow)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    trigger_type: str | None = None,
    is_active: bool | None = None,
) -> PaginatedResponse[WorkflowResponse]:
    stmt = select(Workflow).where(Workflow.workspace_id == current_user.workspace_id)
    if trigger_type is not None:
        stmt = stmt.where(Workflow.trigger_type == trigger_type)
    if is_active is not None:
        stmt = stmt.where(Workflow.is_active.is_(is_active))

    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(Workflow.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    items = [WorkflowResponse.model_validate(w) for w in result.scalars().all()]
    return PaginatedResponse.build(items=items, total=total, params=pagination)


@router.get("/{workflow_id}", response_model=WorkflowDetailResponse)
async def get_workflow(
    workflow_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> WorkflowDetailResponse:
    workflow = await _load_workflow(db, workflow_id, current_user.workspace_id)
    return await _build_detail(db, workflow)


@router.patch("/{workflow_id}", response_model=WorkflowDetailResponse)
async def update_workflow(
    workflow_id: UUID,
    payload: WorkflowUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> WorkflowDetailResponse:
    workflow = await _load_workflow(db, workflow_id, current_user.workspace_id)
    data = payload.model_dump(exclude_unset=True)
    new_conditions = data.pop("conditions", None)
    new_steps = data.pop("steps", None)
    for key, value in data.items():
        setattr(workflow, key, value)

    if new_conditions is not None:
        existing = await db.execute(
            select(WorkflowCondition).where(WorkflowCondition.workflow_id == workflow.id)
        )
        for old in existing.scalars().all():
            await db.delete(old)
        for cond in new_conditions:
            db.add(WorkflowCondition(workflow_id=workflow.id, **cond))

    if new_steps is not None:
        existing = await db.execute(
            select(WorkflowStep).where(WorkflowStep.workflow_id == workflow.id)
        )
        for old in existing.scalars().all():
            await db.delete(old)
        for step in new_steps:
            db.add(WorkflowStep(workflow_id=workflow.id, **step))

    await db.commit()
    await db.refresh(workflow)
    return await _build_detail(db, workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_workflow(
    workflow_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    workflow = await _load_workflow(db, workflow_id, current_user.workspace_id)
    workflow.is_active = False
    await db.commit()


@router.post(
    "/{workflow_id}/trigger",
    response_model=list[WorkflowRunResponse],
    status_code=status.HTTP_201_CREATED,
)
async def manual_trigger(
    workflow_id: UUID,
    payload: WorkflowManualTrigger,
    db: DbSession,
    current_user: CurrentUser,
) -> list[WorkflowRunResponse]:
    """Force-run a specific workflow regardless of its configured trigger_type.

    Conditions still apply. Other workflows with the same trigger_type are
    NOT fired here — for that, use the underlying service hook.
    """
    workflow = await _load_workflow(db, workflow_id, current_user.workspace_id)

    context = dict(payload.context)
    if payload.entity_type and payload.entity_id:
        context.setdefault(f"{payload.entity_type}_id", str(payload.entity_id))

    if not await workflow_engine.evaluate_conditions(db, workflow, context):
        await db.commit()
        return []

    run = await _start_run_for_workflow(
        db,
        workflow=workflow,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        context=context,
    )
    await db.commit()
    return [WorkflowRunResponse.model_validate(run)] if run is not None else []


async def _start_run_for_workflow(
    db: DbSession,
    *,
    workflow: Workflow,
    entity_type: str | None,
    entity_id: UUID | None,
    context: dict,
) -> WorkflowRun | None:
    """Materialise a WorkflowRun + first step run for a single workflow.

    Mirrors the per-workflow branch inside ``workflow_engine.trigger`` so the
    manual endpoint can target a single workflow without fanning out.
    """
    from datetime import UTC, datetime

    from app.models.workflow_step_run import WorkflowStepRun, WorkflowStepRunStatus
    from app.services.workflow_actions import compute_execute_at

    steps_result = await db.execute(
        select(WorkflowStep)
        .where(WorkflowStep.workflow_id == workflow.id)
        .order_by(WorkflowStep.position.asc())
    )
    steps = list(steps_result.scalars().all())

    now = datetime.now(UTC)

    def _coerce(value: object) -> UUID | None:
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (ValueError, AttributeError):
            return None

    contact_id = _coerce(context.get("contact_id"))
    deal_id = _coerce(context.get("deal_id"))

    run = WorkflowRun(
        workspace_id=workflow.workspace_id,
        workflow_id=workflow.id,
        trigger_type="manual",
        trigger_entity_type=entity_type,
        trigger_entity_id=entity_id,
        contact_id=contact_id,
        deal_id=deal_id,
        status=WorkflowRunStatus.COMPLETED if not steps else WorkflowRunStatus.RUNNING,
        current_step_position=0,
    )
    if not steps:
        run.completed_at = now
    db.add(run)
    await db.flush()
    workflow.run_count = (workflow.run_count or 0) + 1
    workflow.last_run_at = now

    if steps:
        first = steps[0]
        step_run = WorkflowStepRun(
            workflow_run_id=run.id,
            workflow_step_id=first.id,
            status=(
                WorkflowStepRunStatus.WAITING_APPROVAL
                if first.requires_approval
                else WorkflowStepRunStatus.PENDING
            ),
            execute_at=compute_execute_at(first.delay_minutes),
        )
        db.add(step_run)
        await db.flush()
        if first.requires_approval:
            run.status = WorkflowRunStatus.WAITING_APPROVAL
            await db.flush()
    return run


# --- workflow runs ----------------------------------------------------------


@runs_router.get("/workflow-runs", response_model=WorkflowRunListResponse)
async def list_runs(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    workflow_id: UUID | None = None,
    status_filter: Annotated[
        WorkflowRunStatus | None, Query(alias="status")
    ] = None,
    contact_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> PaginatedResponse[WorkflowRunResponse]:
    stmt = select(WorkflowRun).where(
        WorkflowRun.workspace_id == current_user.workspace_id
    )
    if workflow_id is not None:
        stmt = stmt.where(WorkflowRun.workflow_id == workflow_id)
    if status_filter is not None:
        stmt = stmt.where(WorkflowRun.status == status_filter)
    if contact_id is not None:
        stmt = stmt.where(WorkflowRun.contact_id == contact_id)
    if since is not None:
        stmt = stmt.where(WorkflowRun.created_at >= since)
    if until is not None:
        stmt = stmt.where(WorkflowRun.created_at <= until)

    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = int(count_result.scalar_one())

    stmt = (
        stmt.order_by(WorkflowRun.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    result = await db.execute(stmt)
    items = [WorkflowRunResponse.model_validate(r) for r in result.scalars().all()]
    return PaginatedResponse.build(items=items, total=total, params=pagination)


@runs_router.get(
    "/workflow-runs/{run_id}", response_model=WorkflowRunDetailResponse
)
async def get_run(
    run_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> WorkflowRunDetailResponse:
    result = await db.execute(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id,
            WorkflowRun.workspace_id == current_user.workspace_id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found"
        )
    step_runs_result = await db.execute(
        select(WorkflowStepRun)
        .where(WorkflowStepRun.workflow_run_id == run.id)
        .order_by(WorkflowStepRun.created_at.asc())
    )
    step_runs = [
        WorkflowStepRunResponse.model_validate(sr)
        for sr in step_runs_result.scalars().all()
    ]
    return WorkflowRunDetailResponse(
        **WorkflowRunResponse.model_validate(run).model_dump(),
        step_runs=step_runs,
    )


@runs_router.post(
    "/workflow-step-runs/{step_run_id}/approve",
    response_model=WorkflowStepRunResponse,
)
async def approve_step_run(
    step_run_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> WorkflowStepRunResponse:
    step_run = await db.get(WorkflowStepRun, step_run_id)
    if step_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Step run not found"
        )
    run = await db.get(WorkflowRun, step_run.workflow_run_id)
    if run is None or run.workspace_id != current_user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Step run not found"
        )

    try:
        await workflow_engine.approve_step(
            db, step_run_id=step_run_id, approved_by_id=current_user.id
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    await db.commit()
    await db.refresh(step_run)
    return WorkflowStepRunResponse.model_validate(step_run)
