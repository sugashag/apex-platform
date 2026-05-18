"""Plan-limit enforcement.

These checks run before write operations. They consult the workspace's
``WorkspaceSubscription`` → ``Plan`` link and raise HTTP 402 ("Payment
Required") when the workspace tries to exceed its plan's limits or use a
capability that its plan doesn't include.

Workspaces with no subscription record are treated as on the most permissive
"unlimited" plan — this keeps legacy data and tests that predate Phase 8
working without explicit setup.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.plan import Plan
from app.models.user import User
from app.models.workspace_subscription import WorkspaceSubscription


async def _get_plan(db: AsyncSession, workspace_id: UUID) -> Plan | None:
    """Return the workspace's plan, or None if no subscription exists yet."""
    result = await db.execute(
        select(Plan)
        .join(WorkspaceSubscription, WorkspaceSubscription.plan_id == Plan.id)
        .where(WorkspaceSubscription.workspace_id == workspace_id)
    )
    return result.scalar_one_or_none()


def _payment_required(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=detail,
    )


async def check_user_limit(db: AsyncSession, workspace_id: UUID) -> None:
    """Raise 402 if the workspace is at or over its plan's ``max_users``."""
    plan = await _get_plan(db, workspace_id)
    if plan is None or plan.max_users is None:
        return
    result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(
            User.workspace_id == workspace_id,
            User.is_active.is_(True),
        )
    )
    current = int(result.scalar_one())
    if current >= plan.max_users:
        raise _payment_required(
            f"Plan limit reached: {plan.name} allows at most "
            f"{plan.max_users} active users. Upgrade to add more."
        )


async def check_contact_limit(db: AsyncSession, workspace_id: UUID) -> None:
    """Raise 402 if the workspace is at or over its plan's ``max_contacts``."""
    plan = await _get_plan(db, workspace_id)
    if plan is None or plan.max_contacts is None:
        return
    result = await db.execute(
        select(func.count())
        .select_from(Contact)
        .where(
            Contact.workspace_id == workspace_id,
            Contact.is_active.is_(True),
        )
    )
    current = int(result.scalar_one())
    if current >= plan.max_contacts:
        raise _payment_required(
            f"Plan limit reached: {plan.name} allows at most "
            f"{plan.max_contacts} contacts. Upgrade for more capacity."
        )


async def check_netsuite_allowed(db: AsyncSession, workspace_id: UUID) -> None:
    """Raise 402 if the workspace's plan does not include NetSuite."""
    plan = await _get_plan(db, workspace_id)
    if plan is None:
        return
    if not plan.includes_netsuite:
        raise _payment_required(
            f"NetSuite integration is not included in the {plan.name} plan. "
            "Upgrade to Growth or Enterprise to connect NetSuite."
        )


async def check_ai_agents_allowed(db: AsyncSession, workspace_id: UUID) -> None:
    """Raise 402 if the workspace's plan does not include AI agents."""
    plan = await _get_plan(db, workspace_id)
    if plan is None:
        return
    if not plan.includes_ai_agents:
        raise _payment_required(
            f"AI agents are not included in the {plan.name} plan. "
            "Upgrade to access AI features."
        )


__all__ = [
    "check_ai_agents_allowed",
    "check_contact_limit",
    "check_netsuite_allowed",
    "check_user_limit",
]
