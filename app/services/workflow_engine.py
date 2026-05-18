"""Workflow engine — trigger evaluation, step scheduling, and execution.

The engine is intentionally small and synchronous-feeling:
- ``trigger`` materialises all matching workflows + their first step runs.
- ``execute_step`` runs one step, then enqueues the next.
- Delays use ``execute_at`` on ``WorkflowStepRun`` — an ARQ cron poller picks
  due rows up.
- Human-approval gates pause the run until ``approve_step`` is called.

All public methods accept an ``AsyncSession`` and DO NOT commit — the caller
is responsible for committing so the engine composes inside other services'
transactions (e.g. ``after_lead_created``). The exception is ``execute_step``,
which is invoked from an ARQ job and commits its own session.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import Workflow
from app.models.workflow_condition import (
    WorkflowCondition,
    WorkflowConditionOperator,
)
from app.models.workflow_run import WorkflowRun, WorkflowRunStatus
from app.models.workflow_step import WorkflowStep
from app.models.workflow_step_run import (
    WorkflowStepRun,
    WorkflowStepRunStatus,
)
from app.services.agent_queue import enqueue
from app.services.template_service import resolve_path
from app.services.workflow_actions import ACTION_HANDLERS, compute_execute_at

logger = logging.getLogger(__name__)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


def evaluate_condition(
    condition: WorkflowCondition, context: dict[str, Any]
) -> bool:
    """Evaluate a single condition against the event context."""
    actual = resolve_path(condition.field, context)
    expected = condition.value
    op = condition.operator

    if op == WorkflowConditionOperator.IS_SET:
        return actual is not None and actual != ""
    if op == WorkflowConditionOperator.IS_NOT_SET:
        return actual is None or actual == ""
    if op == WorkflowConditionOperator.EQUALS:
        return str(actual) == str(expected) if actual is not None else expected is None
    if op == WorkflowConditionOperator.NOT_EQUALS:
        return str(actual) != str(expected)
    if op == WorkflowConditionOperator.GREATER_THAN:
        a, b = _to_float(actual), _to_float(expected)
        return a is not None and b is not None and a > b
    if op == WorkflowConditionOperator.LESS_THAN:
        a, b = _to_float(actual), _to_float(expected)
        return a is not None and b is not None and a < b
    if op == WorkflowConditionOperator.CONTAINS:
        return expected is not None and expected in (str(actual) if actual else "")
    if op == WorkflowConditionOperator.NOT_CONTAINS:
        return expected is None or expected not in (str(actual) if actual else "")
    return False


async def _load_conditions(
    db: AsyncSession, workflow_id: UUID
) -> list[WorkflowCondition]:
    result = await db.execute(
        select(WorkflowCondition)
        .where(WorkflowCondition.workflow_id == workflow_id)
        .order_by(WorkflowCondition.position.asc())
    )
    return list(result.scalars().all())


async def evaluate_conditions(
    db: AsyncSession, workflow: Workflow, context: dict[str, Any]
) -> bool:
    """All-must-pass evaluation. An empty condition list always passes."""
    conditions = await _load_conditions(db, workflow.id)
    for cond in conditions:
        if not evaluate_condition(cond, context):
            return False
    return True


async def _load_steps(
    db: AsyncSession, workflow_id: UUID
) -> list[WorkflowStep]:
    result = await db.execute(
        select(WorkflowStep)
        .where(WorkflowStep.workflow_id == workflow_id)
        .order_by(WorkflowStep.position.asc())
    )
    return list(result.scalars().all())


async def trigger(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    trigger_type: str,
    entity_type: str | None,
    entity_id: UUID | None,
    context: dict[str, Any],
) -> list[WorkflowRun]:
    """Find all matching active workflows and start their first steps.

    Returns the WorkflowRun records created. Caller commits.
    """
    # Ensure standard keys are present so condition paths like
    # `workspace_id` / `contact_id` resolve.
    context.setdefault("workspace_id", str(workspace_id))
    if entity_type and entity_id:
        context.setdefault(f"{entity_type}_id", str(entity_id))

    result = await db.execute(
        select(Workflow).where(
            Workflow.workspace_id == workspace_id,
            Workflow.trigger_type == trigger_type,
            Workflow.is_active.is_(True),
        )
    )
    workflows = list(result.scalars().all())

    created: list[WorkflowRun] = []
    now = datetime.now(UTC)

    for workflow in workflows:
        if not await evaluate_conditions(db, workflow, context):
            continue

        steps = await _load_steps(db, workflow.id)

        contact_id = _coerce_uuid(context.get("contact_id"))
        deal_id = _coerce_uuid(context.get("deal_id"))

        run = WorkflowRun(
            workspace_id=workspace_id,
            workflow_id=workflow.id,
            trigger_type=trigger_type,
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
            else:
                await _enqueue_step(step_run.id)

        created.append(run)

    return created


async def _enqueue_step(step_run_id: UUID) -> None:
    """Best-effort enqueue. ARQ-down fall-throughs are picked up by the
    scheduler cron that polls `execute_at`.
    """
    await enqueue(
        "execute_workflow_step",
        # workspace_id is not strictly needed for this job — the worker reloads
        # from the step_run row — so we pass a dummy uuid here. ``enqueue``'s
        # signature expects ``(job_name, workspace_id, entity_id, **kwargs)``.
        UUID(int=0),
        step_run_id,
    )


async def execute_step(db: AsyncSession, step_run_id: UUID) -> None:
    """Execute one WorkflowStepRun.

    1. Load the step run, its parent step, and the workflow run.
    2. If waiting on approval, do nothing.
    3. Mark running, call the handler, mark completed/failed.
    4. Enqueue the next step (or close out the run).
    Commits at the end so the ARQ job is self-contained.
    """
    step_run = await db.get(WorkflowStepRun, step_run_id)
    if step_run is None:
        logger.warning("execute_step: missing step_run %s", step_run_id)
        return

    if step_run.status not in (
        WorkflowStepRunStatus.PENDING,
        WorkflowStepRunStatus.APPROVED,
    ):
        logger.debug(
            "execute_step: step_run %s is %s — skipping",
            step_run_id,
            step_run.status,
        )
        return

    step = await db.get(WorkflowStep, step_run.workflow_step_id)
    run = await db.get(WorkflowRun, step_run.workflow_run_id)
    if step is None or run is None:
        logger.warning(
            "execute_step: missing step or run for %s", step_run_id
        )
        return

    now = datetime.now(UTC)
    step_run.status = WorkflowStepRunStatus.RUNNING
    step_run.started_at = now
    await db.flush()

    context = await _rehydrate_context(db, run)
    handler = ACTION_HANDLERS.get(step.action_type.value)

    if handler is None:
        step_run.status = WorkflowStepRunStatus.FAILED
        step_run.error_message = f"no handler for action {step.action_type.value}"
        step_run.completed_at = datetime.now(UTC)
        run.status = WorkflowRunStatus.FAILED
        run.error_message = step_run.error_message
        run.completed_at = step_run.completed_at
        await db.commit()
        return

    try:
        output = await handler(db, step_run, step, context)
        step_run.output = output
        step_run.status = WorkflowStepRunStatus.COMPLETED
        step_run.completed_at = datetime.now(UTC)
    except Exception as exc:  # noqa: BLE001 — record + halt
        logger.exception("workflow step %s failed", step_run_id)
        step_run.status = WorkflowStepRunStatus.FAILED
        step_run.error_message = str(exc)
        step_run.completed_at = datetime.now(UTC)
        run.status = WorkflowRunStatus.FAILED
        run.error_message = str(exc)
        run.completed_at = step_run.completed_at
        await db.commit()
        return

    await _advance_or_complete(db, run, step)
    await db.commit()


async def _rehydrate_context(
    db: AsyncSession, run: WorkflowRun
) -> dict[str, Any]:
    """Rebuild the action context from a WorkflowRun.

    The trigger context is not persisted — we only need stable foreign keys
    to drive the action handlers, plus the contact/deal records for template
    substitution.
    """
    from app.models.contact import Contact
    from app.models.deal import Deal
    from app.models.workspace import Workspace

    context: dict[str, Any] = {
        "workspace_id": str(run.workspace_id),
        "workflow_id": str(run.workflow_id),
        "workflow_run_id": str(run.id),
        "trigger_type": run.trigger_type,
    }

    if run.contact_id is not None:
        context["contact_id"] = str(run.contact_id)
        contact = await db.get(Contact, run.contact_id)
        if contact is not None:
            context["contact"] = {
                "id": str(contact.id),
                "email": contact.email,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "phone": contact.phone,
                "title": contact.title,
                "source": contact.source,
                "lead_score": contact.lead_score,
            }

    if run.deal_id is not None:
        context["deal_id"] = str(run.deal_id)
        deal = await db.get(Deal, run.deal_id)
        if deal is not None:
            context["deal"] = {
                "id": str(deal.id),
                "name": deal.name,
                "value": (deal.value_cents or 0) / 100,
                "value_cents": deal.value_cents,
                "currency": deal.currency,
                "probability": deal.probability,
                "stage_id": str(deal.pipeline_stage_id) if deal.pipeline_stage_id else None,
            }

    workspace = await db.get(Workspace, run.workspace_id)
    if workspace is not None:
        context["workspace"] = {
            "id": str(workspace.id),
            "name": workspace.name,
            "slug": workspace.slug,
        }
    return context


async def _advance_or_complete(
    db: AsyncSession, run: WorkflowRun, just_finished: WorkflowStep
) -> None:
    """Find the next step in the workflow and schedule it, or finalize."""
    next_step_result = await db.execute(
        select(WorkflowStep)
        .where(
            WorkflowStep.workflow_id == run.workflow_id,
            WorkflowStep.position > just_finished.position,
        )
        .order_by(WorkflowStep.position.asc())
        .limit(1)
    )
    next_step = next_step_result.scalar_one_or_none()

    if next_step is None:
        run.status = WorkflowRunStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        return

    run.current_step_position = next_step.position
    next_run = WorkflowStepRun(
        workflow_run_id=run.id,
        workflow_step_id=next_step.id,
        status=(
            WorkflowStepRunStatus.WAITING_APPROVAL
            if next_step.requires_approval
            else WorkflowStepRunStatus.PENDING
        ),
        execute_at=compute_execute_at(next_step.delay_minutes),
    )
    db.add(next_run)
    await db.flush()

    if next_step.requires_approval:
        run.status = WorkflowRunStatus.WAITING_APPROVAL
    elif next_step.delay_minutes <= 0:
        await _enqueue_step(next_run.id)


async def approve_step(
    db: AsyncSession,
    *,
    step_run_id: UUID,
    approved_by_id: UUID,
) -> WorkflowStepRun:
    """Approve a waiting_approval step and resume the workflow.

    Caller commits. The actual execution happens when the ARQ job (or the
    cron poller) picks the step up.
    """
    step_run = await db.get(WorkflowStepRun, step_run_id)
    if step_run is None:
        raise ValueError("step_run not found")
    if step_run.status != WorkflowStepRunStatus.WAITING_APPROVAL:
        raise ValueError(
            f"step_run is {step_run.status}, not waiting_approval"
        )

    step_run.status = WorkflowStepRunStatus.APPROVED
    step_run.approved_by_id = approved_by_id
    step_run.approved_at = datetime.now(UTC)

    run = await db.get(WorkflowRun, step_run.workflow_run_id)
    if run is not None and run.status == WorkflowRunStatus.WAITING_APPROVAL:
        run.status = WorkflowRunStatus.RUNNING

    await db.flush()
    await _enqueue_step(step_run.id)
    return step_run


async def cancel_run(db: AsyncSession, run_id: UUID) -> WorkflowRun | None:
    """Cancel a workflow run + any non-terminal step runs."""
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        return None
    if run.status in (WorkflowRunStatus.COMPLETED, WorkflowRunStatus.FAILED):
        return run

    run.status = WorkflowRunStatus.CANCELLED
    run.completed_at = datetime.now(UTC)

    step_runs = await db.execute(
        select(WorkflowStepRun).where(
            WorkflowStepRun.workflow_run_id == run.id,
            WorkflowStepRun.status.in_(
                [
                    WorkflowStepRunStatus.PENDING,
                    WorkflowStepRunStatus.WAITING_APPROVAL,
                    WorkflowStepRunStatus.RUNNING,
                    WorkflowStepRunStatus.APPROVED,
                ]
            ),
        )
    )
    for sr in step_runs.scalars().all():
        sr.status = WorkflowStepRunStatus.SKIPPED
        sr.completed_at = run.completed_at
    await db.flush()
    return run


async def process_due_step_runs(db: AsyncSession) -> int:
    """Cron-poller helper: pick up pending step runs whose `execute_at` is due.

    The trigger path enqueues steps directly via ARQ when delay_minutes==0,
    so this exists primarily to catch:
      - delayed steps that need to fire later
      - cases where Redis was unavailable at enqueue time

    Returns the number of step runs queued.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(WorkflowStepRun.id).where(
            WorkflowStepRun.status == WorkflowStepRunStatus.PENDING,
            WorkflowStepRun.execute_at <= now,
        )
    )
    ids = [row[0] for row in result.all()]
    for step_run_id in ids:
        await _enqueue_step(step_run_id)
    return len(ids)


# --- public re-exports so callers can import from one place -----------------


async def trigger_workflow(  # noqa: D401 — pragmatic alias
    db: AsyncSession,
    *,
    workspace_id: UUID,
    trigger_type: str,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    context: dict[str, Any] | None = None,
) -> list[WorkflowRun]:
    """Convenience wrapper used by service-level hooks.

    Never raises — workflow plumbing must not block the originating action.
    """
    try:
        return await trigger(
            db,
            workspace_id=workspace_id,
            trigger_type=trigger_type,
            entity_type=entity_type,
            entity_id=entity_id,
            context=context or {},
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "workflow trigger failed for %s/%s", trigger_type, entity_id
        )
        return []
