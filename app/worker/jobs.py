"""ARQ job functions — thin wrappers around the agent classes.

Every job:
- opens a fresh AsyncSession against the same DATABASE_URL the API uses
- instantiates the corresponding agent
- delegates to ``agent.execute(...)`` which writes the AgentRun record
- commits + returns the AgentRun id (or raises so ARQ records the failure)
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.agents.call_summarizer import CallSummarizerAgent
from app.agents.lead_scorer import LeadScorerAgent
from app.agents.objection_handler import ObjectionHandlerAgent
from app.agents.outbound_drafter import OutboundDrafterAgent
from app.agents.pipeline_forecaster import PipelineForecasterAgent
from app.agents.reply_drafter import ReplyDrafterAgent
from app.database import SessionLocal
from app.services import (
    netsuite_sync_service,
    reporting_service,
    sequence_service,
    workflow_engine,
)


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _as_optional_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    return _as_uuid(value)


async def run_lead_scorer(
    ctx: dict[str, Any],
    workspace_id: Any,
    entity_id: Any,
    trigger: str = "lead_created",
    **kwargs: Any,
) -> str:
    async with SessionLocal() as db:
        agent = LeadScorerAgent()
        run = await agent.execute(
            db,
            workspace_id=_as_uuid(workspace_id),
            entity_id=_as_optional_uuid(entity_id),
            entity_type="lead",
            trigger=trigger,
            **kwargs,
        )
        await db.commit()
        return str(run.id)


async def run_call_summarizer(
    ctx: dict[str, Any],
    workspace_id: Any,
    entity_id: Any,
    trigger: str = "call_completed",
    **kwargs: Any,
) -> str:
    async with SessionLocal() as db:
        agent = CallSummarizerAgent()
        run = await agent.execute(
            db,
            workspace_id=_as_uuid(workspace_id),
            entity_id=_as_optional_uuid(entity_id),
            entity_type="call",
            trigger=trigger,
            **kwargs,
        )
        await db.commit()
        # Side-effect: if objections were raised, kick off the objection handler.
        objections = (run.output or {}).get("objections_raised") or []
        if objections and ctx.get("redis") is not None:
            await ctx["redis"].enqueue_job(
                "run_objection_handler",
                str(workspace_id),
                str(entity_id),
                objections=objections,
                trigger="call_summarizer",
            )
        return str(run.id)


async def run_outbound_drafter(
    ctx: dict[str, Any],
    workspace_id: Any,
    entity_id: Any,
    trigger: str = "manual",
    **kwargs: Any,
) -> str:
    async with SessionLocal() as db:
        agent = OutboundDrafterAgent()
        run = await agent.execute(
            db,
            workspace_id=_as_uuid(workspace_id),
            entity_id=_as_optional_uuid(entity_id),
            entity_type="contact",
            trigger=trigger,
            **kwargs,
        )
        await db.commit()
        return str(run.id)


async def run_reply_drafter(
    ctx: dict[str, Any],
    workspace_id: Any,
    entity_id: Any,
    trigger: str = "inbound_message",
    **kwargs: Any,
) -> str:
    async with SessionLocal() as db:
        agent = ReplyDrafterAgent()
        run = await agent.execute(
            db,
            workspace_id=_as_uuid(workspace_id),
            entity_id=_as_optional_uuid(entity_id),
            entity_type="thread",
            trigger=trigger,
            **kwargs,
        )
        await db.commit()
        return str(run.id)


async def run_objection_handler(
    ctx: dict[str, Any],
    workspace_id: Any,
    entity_id: Any,
    trigger: str = "call_summarizer",
    **kwargs: Any,
) -> str:
    async with SessionLocal() as db:
        agent = ObjectionHandlerAgent()
        run = await agent.execute(
            db,
            workspace_id=_as_uuid(workspace_id),
            entity_id=_as_optional_uuid(entity_id),
            entity_type="call",
            trigger=trigger,
            **kwargs,
        )
        await db.commit()
        return str(run.id)


async def execute_workflow_step(
    ctx: dict[str, Any],
    _workspace_id: Any,
    step_run_id: Any,
    **_: Any,
) -> str:
    """Run one WorkflowStepRun. The engine commits internally."""
    async with SessionLocal() as db:
        await workflow_engine.execute_step(db, _as_uuid(step_run_id))
    return str(step_run_id)


async def process_sequences(
    ctx: dict[str, Any],
    workspace_id: Any = None,
    *_: Any,
    **__: Any,
) -> int:
    """Advance any sequence enrollments whose next_step_at has elapsed."""
    async with SessionLocal() as db:
        count = await sequence_service.process_due_steps(
            db,
            workspace_id=_as_optional_uuid(workspace_id),
        )
        await db.commit()
        return count


async def process_workflow_step_queue(
    ctx: dict[str, Any], *_: Any, **__: Any
) -> int:
    """Catch-up scheduler: enqueue any pending step runs whose execute_at is due."""
    async with SessionLocal() as db:
        count = await workflow_engine.process_due_step_runs(db)
    return count


async def run_pipeline_forecaster(
    ctx: dict[str, Any],
    workspace_id: Any,
    trigger: str = "weekly_cron",
    **kwargs: Any,
) -> str:
    """Generate a fresh PipelineForecast for the workspace."""
    async with SessionLocal() as db:
        agent = PipelineForecasterAgent()
        run = await agent.execute(
            db,
            workspace_id=_as_uuid(workspace_id),
            entity_id=None,
            entity_type="workspace",
            trigger=trigger,
            **kwargs,
        )
        await db.commit()
        return str(run.id)


async def refresh_dashboard_metrics(
    ctx: dict[str, Any],
    workspace_id: Any,
    **_: Any,
) -> str:
    """Recompute and cache the dashboard payload for the workspace."""
    async with SessionLocal() as db:
        await reporting_service.compute_and_cache_metrics(
            db, _as_uuid(workspace_id)
        )
        await db.commit()
        return str(workspace_id)


async def run_pipeline_forecaster_for_active_workspaces(
    ctx: dict[str, Any], *_: Any, **__: Any
) -> int:
    """Cron fan-out: enqueue a forecaster run for each active workspace."""
    from sqlalchemy import select

    from app.models.workspace import Workspace

    redis = ctx.get("redis")
    if redis is None:
        return 0

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Workspace.id).where(Workspace.is_active.is_(True))
            )
        ).all()
    fired = 0
    for (ws_id,) in rows:
        await redis.enqueue_job(
            "run_pipeline_forecaster", str(ws_id), trigger="weekly_cron"
        )
        fired += 1
    return fired


async def refresh_dashboard_metrics_for_active_workspaces(
    ctx: dict[str, Any], *_: Any, **__: Any
) -> int:
    """Cron fan-out: enqueue a dashboard refresh for each active workspace."""
    from sqlalchemy import select

    from app.models.workspace import Workspace

    redis = ctx.get("redis")
    if redis is None:
        return 0

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Workspace.id).where(Workspace.is_active.is_(True))
            )
        ).all()
    fired = 0
    for (ws_id,) in rows:
        await redis.enqueue_job("refresh_dashboard_metrics", str(ws_id))
        fired += 1
    return fired


async def sync_company_to_netsuite(
    ctx: dict[str, Any],
    workspace_id: Any,
    company_id: Any,
    **_: Any,
) -> str:
    """Sync a Company to NetSuite as a Customer."""
    async with SessionLocal() as db:
        log = await netsuite_sync_service.sync_company_as_customer(
            db, _as_uuid(workspace_id), _as_uuid(company_id)
        )
        await db.commit()
        return str(log.id)


async def sync_deal_to_netsuite(
    ctx: dict[str, Any],
    workspace_id: Any,
    deal_id: Any,
    **_: Any,
) -> str:
    """Sync a Deal to NetSuite as a Sales Order."""
    async with SessionLocal() as db:
        log = await netsuite_sync_service.sync_deal_as_sales_order(
            db, _as_uuid(workspace_id), _as_uuid(deal_id)
        )
        await db.commit()
        return str(log.id)


async def sync_payment_to_netsuite(
    ctx: dict[str, Any],
    workspace_id: Any,
    payment_id: Any,
    **_: Any,
) -> str:
    """Sync a Payment to NetSuite as an Invoice."""
    async with SessionLocal() as db:
        log = await netsuite_sync_service.sync_payment_as_invoice(
            db, _as_uuid(workspace_id), _as_uuid(payment_id)
        )
        await db.commit()
        return str(log.id)


async def sync_msa_to_netsuite(
    ctx: dict[str, Any],
    workspace_id: Any,
    msa_id: Any,
    **_: Any,
) -> str:
    """Upload an MSA PDF to NetSuite File Cabinet and attach to the Sales Order."""
    async with SessionLocal() as db:
        log = await netsuite_sync_service.sync_msa_document(
            db, _as_uuid(workspace_id), _as_uuid(msa_id)
        )
        await db.commit()
        return str(log.id)


async def retry_netsuite_syncs(
    ctx: dict[str, Any], *_: Any, **__: Any
) -> int:
    """Cron fan-out: retry all failed NetSuite syncs across workspaces."""
    from sqlalchemy import select

    from app.models.workspace import Workspace

    retried = 0
    async with SessionLocal() as db:
        ws_rows = (
            await db.execute(
                select(Workspace.id).where(Workspace.is_active.is_(True))
            )
        ).all()
        for (ws_id,) in ws_rows:
            retried += await netsuite_sync_service.retry_failed_syncs(db, ws_id)
        await db.commit()
    return retried


async def check_sla_breaches(ctx: dict[str, Any], *_: Any, **__: Any) -> int:
    """Detect SLA breaches on open threads and fire the workflow engine."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.models.thread import Thread, ThreadStatus

    now = datetime.now(UTC)
    fired = 0

    async with SessionLocal() as db:
        first_resp_result = await db.execute(
            select(Thread).where(
                Thread.status == ThreadStatus.OPEN,
                Thread.first_responded_at.is_(None),
                Thread.sla_first_response_due_at.is_not(None),
                Thread.sla_first_response_due_at < now,
            )
        )
        for thread in first_resp_result.scalars().all():
            await workflow_engine.trigger_workflow(
                db,
                workspace_id=thread.workspace_id,
                trigger_type="sla_breached",
                entity_type="thread",
                entity_id=thread.id,
                context={
                    "thread_id": str(thread.id),
                    "contact_id": str(thread.contact_id) if thread.contact_id else None,
                    "deal_id": str(thread.deal_id) if thread.deal_id else None,
                    "breach_type": "first_response",
                },
            )
            fired += 1

        resolution_result = await db.execute(
            select(Thread).where(
                Thread.status == ThreadStatus.OPEN,
                Thread.sla_resolution_due_at.is_not(None),
                Thread.sla_resolution_due_at < now,
            )
        )
        for thread in resolution_result.scalars().all():
            await workflow_engine.trigger_workflow(
                db,
                workspace_id=thread.workspace_id,
                trigger_type="sla_breached",
                entity_type="thread",
                entity_id=thread.id,
                context={
                    "thread_id": str(thread.id),
                    "contact_id": str(thread.contact_id) if thread.contact_id else None,
                    "deal_id": str(thread.deal_id) if thread.deal_id else None,
                    "breach_type": "resolution",
                },
            )
            fired += 1

        await db.commit()
    return fired
