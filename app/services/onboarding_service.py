"""Workspace onboarding checklist orchestration.

The checklist tracks whether the workspace has completed key activation
milestones. ``evaluate_checklist`` walks the underlying tables and flips
each flag based on actual data so onboarding state stays self-healing even
when users skip the explicit "mark complete" call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import Call
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email_account import EmailAccount
from app.models.netsuite_config import NetSuiteConfig, NetSuiteTestStatus
from app.models.onboarding_checklist import CHECKLIST_STEPS, OnboardingChecklist
from app.models.pipeline_stage import PipelineStage
from app.models.sms_message import SmsMessage
from app.models.user import User
from app.models.visitor_session import VisitorSession
from app.models.workflow import Workflow

DEFAULT_PIPELINE_STAGE_COUNT = 6


async def get_or_create_checklist(
    db: AsyncSession, workspace_id: UUID
) -> OnboardingChecklist:
    """Return the workspace's checklist, creating it if missing."""
    result = await db.execute(
        select(OnboardingChecklist).where(
            OnboardingChecklist.workspace_id == workspace_id
        )
    )
    checklist = result.scalar_one_or_none()
    if checklist is None:
        checklist = OnboardingChecklist(workspace_id=workspace_id)
        db.add(checklist)
        await db.flush()
    return checklist


async def mark_step_complete(
    db: AsyncSession,
    workspace_id: UUID,
    step: str,
) -> OnboardingChecklist:
    """Flip ``step`` to True. Stamps ``completed_at`` when all steps are done."""
    if step not in CHECKLIST_STEPS:
        raise ValueError(f"Unknown onboarding step: {step}")

    checklist = await get_or_create_checklist(db, workspace_id)
    setattr(checklist, step, True)

    if checklist.all_steps_done() and checklist.completed_at is None:
        checklist.completed_at = datetime.now(tz=UTC)

    await db.flush()
    return checklist


async def _count(db: AsyncSession, stmt: Any) -> int:
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def evaluate_checklist(
    db: AsyncSession, workspace_id: UUID
) -> OnboardingChecklist:
    """Reconcile checklist flags against actual workspace data."""
    checklist = await get_or_create_checklist(db, workspace_id)

    user_count = await _count(
        db,
        select(func.count())
        .select_from(User)
        .where(User.workspace_id == workspace_id, User.is_active.is_(True)),
    )
    email_account_count = await _count(
        db,
        select(func.count())
        .select_from(EmailAccount)
        .where(EmailAccount.workspace_id == workspace_id),
    )
    call_count = await _count(
        db,
        select(func.count())
        .select_from(Call)
        .where(Call.workspace_id == workspace_id),
    )
    sms_count = await _count(
        db,
        select(func.count())
        .select_from(SmsMessage)
        .where(SmsMessage.workspace_id == workspace_id),
    )
    contact_count = await _count(
        db,
        select(func.count())
        .select_from(Contact)
        .where(
            Contact.workspace_id == workspace_id,
            Contact.is_active.is_(True),
        ),
    )
    deal_count = await _count(
        db,
        select(func.count())
        .select_from(Deal)
        .where(Deal.workspace_id == workspace_id),
    )
    stage_count = await _count(
        db,
        select(func.count())
        .select_from(PipelineStage)
        .where(PipelineStage.workspace_id == workspace_id),
    )
    workflow_count = await _count(
        db,
        select(func.count())
        .select_from(Workflow)
        .where(Workflow.workspace_id == workspace_id),
    )
    visitor_count = await _count(
        db,
        select(func.count())
        .select_from(VisitorSession)
        .where(VisitorSession.workspace_id == workspace_id),
    )
    netsuite_result = await db.execute(
        select(NetSuiteConfig).where(
            NetSuiteConfig.workspace_id == workspace_id
        )
    )
    netsuite_config = netsuite_result.scalar_one_or_none()

    checklist.invite_team_member = user_count > 1
    checklist.connect_email = email_account_count > 0
    checklist.connect_twilio = (call_count + sms_count) > 0
    checklist.import_contacts = contact_count >= 5
    checklist.create_first_deal = deal_count > 0
    checklist.configure_pipeline = stage_count > DEFAULT_PIPELINE_STAGE_COUNT
    checklist.set_up_workflow = workflow_count > 0
    checklist.connect_netsuite = (
        netsuite_config is not None
        and netsuite_config.last_test_status == NetSuiteTestStatus.SUCCESS
    )
    checklist.install_tracking_snippet = visitor_count > 0

    if checklist.all_steps_done() and checklist.completed_at is None:
        checklist.completed_at = datetime.now(tz=UTC)

    await db.flush()
    return checklist


__all__ = [
    "evaluate_checklist",
    "get_or_create_checklist",
    "mark_step_complete",
]
