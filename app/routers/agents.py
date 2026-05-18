"""AI agent invocation + run-history endpoints."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.agents.call_summarizer import CallSummarizerAgent
from app.agents.lead_scorer import LeadScorerAgent
from app.agents.outbound_drafter import OutboundDrafterAgent
from app.agents.reply_drafter import ReplyDrafterAgent
from app.dependencies import CurrentUser, DbSession
from app.models.agent_run import AgentRun, AgentRunStatus, AgentType
from app.models.call import Call
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.thread import Thread
from app.schemas.agent_run import (
    AgentRunListResponse,
    AgentRunResponse,
    DraftOutreachRequest,
)
from app.utils.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post(
    "/leads/{lead_id}/score",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_lead_scorer(
    lead_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> AgentRunResponse:
    lead = (
        await db.execute(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.workspace_id == current_user.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    agent = LeadScorerAgent()
    run = await agent.execute(
        db,
        workspace_id=current_user.workspace_id,
        entity_id=lead.id,
        entity_type="lead",
        trigger="manual",
    )
    await db.commit()
    await db.refresh(run)
    return AgentRunResponse.model_validate(run)


@router.post(
    "/calls/{call_id}/summarize",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_call_summarizer(
    call_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> AgentRunResponse:
    call = (
        await db.execute(
            select(Call).where(
                Call.id == call_id,
                Call.workspace_id == current_user.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    if not call.transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Call has no transcript yet",
        )

    agent = CallSummarizerAgent()
    run = await agent.execute(
        db,
        workspace_id=current_user.workspace_id,
        entity_id=call.id,
        entity_type="call",
        trigger="manual",
    )
    await db.commit()
    await db.refresh(run)
    return AgentRunResponse.model_validate(run)


@router.post(
    "/contacts/{contact_id}/draft-outreach",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_outbound_drafter(
    contact_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    payload: Annotated[DraftOutreachRequest, Body()] = DraftOutreachRequest(),
) -> AgentRunResponse:
    contact = (
        await db.execute(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.workspace_id == current_user.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found"
        )

    agent = OutboundDrafterAgent()
    run = await agent.execute(
        db,
        workspace_id=current_user.workspace_id,
        entity_id=contact.id,
        entity_type="contact",
        trigger="manual",
        step_instructions=payload.step_instructions,
    )
    await db.commit()
    await db.refresh(run)
    return AgentRunResponse.model_validate(run)


@router.post(
    "/threads/{thread_id}/draft-reply",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_reply_drafter(
    thread_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> AgentRunResponse:
    thread = (
        await db.execute(
            select(Thread).where(
                Thread.id == thread_id,
                Thread.workspace_id == current_user.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
        )

    agent = ReplyDrafterAgent()
    run = await agent.execute(
        db,
        workspace_id=current_user.workspace_id,
        entity_id=thread.id,
        entity_type="thread",
        trigger="manual",
    )
    await db.commit()
    await db.refresh(run)
    return AgentRunResponse.model_validate(run)


@router.get("/runs", response_model=AgentRunListResponse)
async def list_agent_runs(
    db: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    agent_type: Annotated[AgentType | None, Query()] = None,
    status_filter: Annotated[
        AgentRunStatus | None, Query(alias="status")
    ] = None,
    entity_id: UUID | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> PaginatedResponse[AgentRunResponse]:
    stmt = select(AgentRun).where(
        AgentRun.workspace_id == current_user.workspace_id
    )
    if agent_type is not None:
        stmt = stmt.where(AgentRun.agent_type == agent_type)
    if status_filter is not None:
        stmt = stmt.where(AgentRun.status == status_filter)
    if entity_id is not None:
        stmt = stmt.where(AgentRun.entity_id == entity_id)
    if created_after is not None:
        stmt = stmt.where(AgentRun.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(AgentRun.created_at <= created_before)

    total = int(
        (await db.execute(select(func.count()).select_from(stmt.subquery())))
        .scalar_one()
    )

    stmt = (
        stmt.order_by(AgentRun.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    rows = [
        AgentRunResponse.model_validate(r)
        for r in (await db.execute(stmt)).scalars().all()
    ]
    return PaginatedResponse.build(items=rows, total=total, params=pagination)


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    run_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> AgentRunResponse:
    run = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.workspace_id == current_user.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found"
        )
    return AgentRunResponse.model_validate(run)
