"""Assignment-rule evaluation — pick a user_id for a freshly arrived thread."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment_rule import AssignmentConditionOperator, AssignmentRule
from app.models.contact import Contact
from app.models.message import Message
from app.models.thread import Thread


def _match(operator: AssignmentConditionOperator, candidate: str, target: str) -> bool:
    cand = candidate.lower()
    tgt = target.lower()
    match operator:
        case AssignmentConditionOperator.EQUALS:
            return cand == tgt
        case AssignmentConditionOperator.CONTAINS:
            return tgt in cand
        case AssignmentConditionOperator.STARTS_WITH:
            return cand.startswith(tgt)
        case AssignmentConditionOperator.ENDS_WITH:
            return cand.endswith(tgt)


async def evaluate_rules(
    db: AsyncSession,
    workspace_id: UUID,
    thread: Thread,
) -> UUID | None:
    """Evaluate active rules in `position` order; return the first match's user id."""
    rules_result = await db.execute(
        select(AssignmentRule)
        .where(
            AssignmentRule.workspace_id == workspace_id,
            AssignmentRule.is_active.is_(True),
        )
        .order_by(AssignmentRule.position.asc(), AssignmentRule.created_at.asc())
    )
    rules = list(rules_result.scalars().all())
    if not rules:
        return None

    # Pull a few extra fields needed for rule matching.
    first_msg_result = await db.execute(
        select(Message)
        .where(Message.thread_id == thread.id)
        .order_by(Message.created_at.asc())
        .limit(1)
    )
    first_message = first_msg_result.scalar_one_or_none()

    contact_source: str | None = None
    if thread.contact_id is not None:
        contact_result = await db.execute(
            select(Contact.source).where(Contact.id == thread.contact_id)
        )
        contact_source = contact_result.scalar_one_or_none()

    for rule in rules:
        candidate: str | None = None
        match rule.condition_field:
            case "from_email":
                candidate = first_message.from_email if first_message else None
            case "subject_contains" | "subject":
                candidate = thread.subject
            case "contact_source":
                candidate = contact_source
            case _:
                continue

        if candidate is None:
            continue
        if _match(rule.condition_operator, candidate, rule.condition_value):
            return rule.assign_to_user_id

    return None
