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
from app.agents.reply_drafter import ReplyDrafterAgent
from app.database import SessionLocal


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
