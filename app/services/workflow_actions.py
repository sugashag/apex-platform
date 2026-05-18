"""Workflow action handlers.

Each handler runs inside the workflow engine's transaction. Handlers return
a JSON-serialisable dict that is stored on `WorkflowStepRun.output` for the
audit trail. They should NOT commit — the engine commits at the end of
`execute_step`.

External side-effects (sending email, SMS, enqueuing agents) degrade
gracefully when the underlying service is unconfigured so workflows still
exercise their full path in CI and local dev.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.activity import Activity, ActivityType, ActorType
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email_account import EmailAccount
from app.models.pipeline_stage import PipelineStage
from app.models.thread import Thread
from app.models.workflow_step import WorkflowStep
from app.models.workflow_step_run import WorkflowStepRun
from app.services.agent_queue import enqueue
from app.services.email_service import email_service
from app.services.template_service import render_template
from app.services.twilio_service import twilio_service

logger = logging.getLogger(__name__)

ActionHandler = Any  # type: callable returning awaitable dict[str, Any]


# --- helpers ----------------------------------------------------------------


def _coerce_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


async def _load_target_contact(
    db: AsyncSession, context: dict[str, Any]
) -> Contact | None:
    cid = _coerce_uuid(context.get("contact_id"))
    if cid is None:
        return None
    result = await db.execute(select(Contact).where(Contact.id == cid))
    return result.scalar_one_or_none()


async def _load_target_deal(
    db: AsyncSession, context: dict[str, Any]
) -> Deal | None:
    did = _coerce_uuid(context.get("deal_id"))
    if did is None:
        return None
    result = await db.execute(select(Deal).where(Deal.id == did))
    return result.scalar_one_or_none()


# --- handlers ---------------------------------------------------------------


async def action_send_email(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Send an email via EmailService.

    action_config keys:
      - to_field: dotted path into context (default 'contact.email')
      - subject: template string
      - body_text: template string
      - body_html: template string
      - from_account_id: optional EmailAccount UUID
    """
    cfg = step.action_config or {}
    contact = await _load_target_contact(db, context)
    deal = await _load_target_deal(db, context)

    to_field = cfg.get("to_field", "contact.email")
    to_address = render_template("{{" + to_field + "}}", context)
    if not to_address and contact is not None:
        to_address = contact.email
    if not to_address:
        return {"skipped": True, "reason": "no recipient resolvable"}

    subject = render_template(cfg.get("subject"), context) or "(no subject)"
    body_html = render_template(cfg.get("body_html"), context) or None
    body_text = render_template(cfg.get("body_text"), context) or None

    workspace_id: UUID = _coerce_uuid(context.get("workspace_id"))  # type: ignore[assignment]

    from_account: EmailAccount | None = None
    from_account_id = _coerce_uuid(cfg.get("from_account_id"))
    if from_account_id is not None:
        result = await db.execute(
            select(EmailAccount).where(
                EmailAccount.id == from_account_id,
                EmailAccount.workspace_id == workspace_id,
            )
        )
        from_account = result.scalar_one_or_none()

    thread = Thread(
        workspace_id=workspace_id,
        contact_id=contact.id if contact is not None else None,
        deal_id=deal.id if deal is not None else None,
        email_account_id=from_account.id if from_account is not None else None,
        subject=subject,
    )
    db.add(thread)
    await db.flush()

    message = await email_service.send_message(
        db,
        thread,
        body_text=body_text,
        body_html=body_html,
        from_account=from_account,
        actor_id=None,
        to_emails=[to_address],
    )
    return {
        "thread_id": str(thread.id),
        "message_id": str(message.id),
        "to": to_address,
        "subject": subject,
    }


async def action_send_sms(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Send an SMS via TwilioService.

    action_config keys:
      - to_field: dotted path (default 'contact.phone')
      - body: template string
      - from_number: optional sender number override
    """
    cfg = step.action_config or {}
    contact = await _load_target_contact(db, context)

    to_field = cfg.get("to_field", "contact.phone")
    to_number = render_template("{{" + to_field + "}}", context)
    if not to_number and contact is not None:
        to_number = contact.phone or ""
    if not to_number:
        return {"skipped": True, "reason": "no destination number resolvable"}

    body = render_template(cfg.get("body"), context)
    from_number = cfg.get("from_number") or settings.TWILIO_FROM_NUMBER or "+15555555555"

    sid = await twilio_service.send_sms(to_number, from_number, body)
    return {"twilio_sid": sid, "to": to_number}


async def action_create_task(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Create a 'task' Activity attached to the workflow's target entity.

    action_config keys:
      - subject: template string
      - body: template string
      - assign_to_id: user UUID
      - due_in_hours: int (stored in meta)
    """
    cfg = step.action_config or {}
    workspace_id: UUID = _coerce_uuid(context.get("workspace_id"))  # type: ignore[assignment]
    contact = await _load_target_contact(db, context)
    deal = await _load_target_deal(db, context)
    assign_to = _coerce_uuid(cfg.get("assign_to_id"))

    subject = render_template(cfg.get("subject"), context) or "Follow up"
    body = render_template(cfg.get("body"), context) or None

    activity = Activity(
        workspace_id=workspace_id,
        contact_id=contact.id if contact is not None else None,
        deal_id=deal.id if deal is not None else None,
        actor_id=assign_to,
        type=ActivityType.TASK,
        actor_type=ActorType.AI_AGENT,
        subject=subject,
        body=body,
        meta={
            "assigned_to_id": str(assign_to) if assign_to else None,
            "due_in_hours": cfg.get("due_in_hours"),
        },
    )
    db.add(activity)
    await db.flush()
    return {"activity_id": str(activity.id), "subject": subject}


async def action_assign_owner(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Set the owner_id on the target contact or deal.

    action_config keys:
      - assign_to_id: user UUID
      - entity_type: 'contact' | 'deal' (default 'contact')
    """
    cfg = step.action_config or {}
    assign_to = _coerce_uuid(cfg.get("assign_to_id"))
    if assign_to is None:
        return {"skipped": True, "reason": "assign_to_id missing"}

    entity_type = cfg.get("entity_type", "contact")
    if entity_type == "deal":
        deal = await _load_target_deal(db, context)
        if deal is None:
            return {"skipped": True, "reason": "no deal in context"}
        deal.owner_id = assign_to
        await db.flush()
        return {"entity_type": "deal", "deal_id": str(deal.id), "owner_id": str(assign_to)}

    contact = await _load_target_contact(db, context)
    if contact is None:
        return {"skipped": True, "reason": "no contact in context"}
    contact.owner_id = assign_to
    await db.flush()
    return {
        "entity_type": "contact",
        "contact_id": str(contact.id),
        "owner_id": str(assign_to),
    }


async def action_update_field(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Mutate a single column on a contact or deal.

    action_config keys:
      - entity_type: 'contact' | 'deal'
      - field: column name
      - value: literal value (template-rendered if string)
    """
    cfg = step.action_config or {}
    entity_type = cfg.get("entity_type", "contact")
    field = cfg.get("field")
    value = cfg.get("value")
    if not field:
        return {"skipped": True, "reason": "field missing"}

    if isinstance(value, str):
        value = render_template(value, context)

    if entity_type == "deal":
        deal = await _load_target_deal(db, context)
        if deal is None:
            return {"skipped": True, "reason": "no deal in context"}
        if not hasattr(deal, field):
            return {"skipped": True, "reason": f"unknown deal field: {field}"}
        setattr(deal, field, value)
        await db.flush()
        return {
            "entity_type": "deal",
            "deal_id": str(deal.id),
            "field": field,
            "value": value,
        }

    contact = await _load_target_contact(db, context)
    if contact is None:
        return {"skipped": True, "reason": "no contact in context"}
    if not hasattr(contact, field):
        return {"skipped": True, "reason": f"unknown contact field: {field}"}
    setattr(contact, field, value)
    await db.flush()
    return {
        "entity_type": "contact",
        "contact_id": str(contact.id),
        "field": field,
        "value": value,
    }


async def action_add_tag(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Record a tag on the timeline (tag column doesn't exist on Contact yet).

    Stored as a note Activity so the tag is visible without a schema change.

    action_config keys:
      - tag: string
    """
    cfg = step.action_config or {}
    tag = (cfg.get("tag") or "").strip()
    if not tag:
        return {"skipped": True, "reason": "tag missing"}

    workspace_id: UUID = _coerce_uuid(context.get("workspace_id"))  # type: ignore[assignment]
    contact = await _load_target_contact(db, context)
    deal = await _load_target_deal(db, context)

    activity = Activity(
        workspace_id=workspace_id,
        contact_id=contact.id if contact is not None else None,
        deal_id=deal.id if deal is not None else None,
        type=ActivityType.NOTE,
        actor_type=ActorType.AI_AGENT,
        subject=f"Tagged: {tag}",
        meta={"tag": tag},
    )
    db.add(activity)
    await db.flush()
    return {"tag": tag, "activity_id": str(activity.id)}


async def action_notify_user(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Create a note Activity addressed to a specific user.

    action_config keys:
      - user_id: target user UUID
      - message: template string
    """
    cfg = step.action_config or {}
    workspace_id: UUID = _coerce_uuid(context.get("workspace_id"))  # type: ignore[assignment]
    user_id = _coerce_uuid(cfg.get("user_id"))
    message = render_template(cfg.get("message"), context) or "Workflow notification"
    contact = await _load_target_contact(db, context)
    deal = await _load_target_deal(db, context)

    activity = Activity(
        workspace_id=workspace_id,
        contact_id=contact.id if contact is not None else None,
        deal_id=deal.id if deal is not None else None,
        actor_id=user_id,
        type=ActivityType.NOTE,
        actor_type=ActorType.AI_AGENT,
        subject="Workflow notification",
        body=message,
        meta={"user_id": str(user_id) if user_id else None},
    )
    db.add(activity)
    await db.flush()
    return {
        "user_id": str(user_id) if user_id else None,
        "activity_id": str(activity.id),
        "message": message,
    }


async def action_wait(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Pure wait — the engine's `delay_minutes` already scheduled the gap.

    This handler is the explicit no-op end of a wait step. action_config may
    carry `minutes` for the audit trail.
    """
    return {"waited_minutes": step.delay_minutes}


async def action_human_gate(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Marker action — `requires_approval` on the step does the real pause.

    Returning here means a human approved the gate, so we just record that
    fact in the audit trail.
    """
    return {
        "approved_by_id": str(step_run.approved_by_id)
        if step_run.approved_by_id
        else None,
        "approved_at": step_run.approved_at.isoformat()
        if step_run.approved_at
        else None,
    }


async def action_trigger_agent(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Enqueue an ARQ agent job (best-effort).

    action_config keys:
      - agent_type: name of the ARQ job (e.g. 'run_lead_scorer')
      - entity_type: 'lead' | 'contact' | 'deal' | 'call' | 'thread'
      - entity_id_field: dotted path in context (default '<entity_type>_id')
    """
    cfg = step.action_config or {}
    workspace_id: UUID = _coerce_uuid(context.get("workspace_id"))  # type: ignore[assignment]
    agent_type = cfg.get("agent_type")
    if not agent_type:
        return {"skipped": True, "reason": "agent_type missing"}

    entity_type = cfg.get("entity_type", "contact")
    field = cfg.get("entity_id_field", f"{entity_type}_id")
    entity_id = _coerce_uuid(context.get(field))

    ok = await enqueue(
        agent_type,
        workspace_id,
        entity_id,
        trigger="workflow",
    )
    return {
        "agent_type": agent_type,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
        "enqueued": ok,
    }


async def action_create_activity(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Create an Activity row.

    action_config keys:
      - type: ActivityType value (default 'note')
      - subject: template string
      - body: template string
      - actor_type: 'human' | 'ai_agent' (default 'ai_agent')
    """
    cfg = step.action_config or {}
    workspace_id: UUID = _coerce_uuid(context.get("workspace_id"))  # type: ignore[assignment]
    contact = await _load_target_contact(db, context)
    deal = await _load_target_deal(db, context)

    raw_type = cfg.get("type") or ActivityType.NOTE.value
    try:
        activity_type = ActivityType(raw_type)
    except ValueError:
        activity_type = ActivityType.NOTE

    raw_actor = cfg.get("actor_type") or ActorType.AI_AGENT.value
    try:
        actor = ActorType(raw_actor)
    except ValueError:
        actor = ActorType.AI_AGENT

    subject = render_template(cfg.get("subject"), context) or None
    body = render_template(cfg.get("body"), context) or None

    activity = Activity(
        workspace_id=workspace_id,
        contact_id=contact.id if contact is not None else None,
        deal_id=deal.id if deal is not None else None,
        type=activity_type,
        actor_type=actor,
        subject=subject,
        body=body,
    )
    db.add(activity)
    await db.flush()
    return {
        "activity_id": str(activity.id),
        "type": activity_type.value,
        "subject": subject,
    }


async def action_change_deal_stage(
    db: AsyncSession,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Move the target deal to a new pipeline stage.

    action_config keys:
      - stage_id: UUID of the target stage
    """
    cfg = step.action_config or {}
    stage_id = _coerce_uuid(cfg.get("stage_id"))
    if stage_id is None:
        return {"skipped": True, "reason": "stage_id missing"}

    deal = await _load_target_deal(db, context)
    if deal is None:
        return {"skipped": True, "reason": "no deal in context"}

    result = await db.execute(
        select(PipelineStage).where(
            PipelineStage.id == stage_id,
            PipelineStage.workspace_id == deal.workspace_id,
        )
    )
    stage = result.scalar_one_or_none()
    if stage is None:
        return {"skipped": True, "reason": "stage not in workspace"}

    previous_stage_id = deal.pipeline_stage_id
    deal.pipeline_stage_id = stage.id
    deal.probability = stage.probability_default

    now = datetime.now(UTC)
    if stage.is_won:
        deal.closed_at = now
    elif stage.is_lost:
        deal.closed_at = now

    activity = Activity(
        workspace_id=deal.workspace_id,
        deal_id=deal.id,
        contact_id=deal.contact_id,
        type=ActivityType.STAGE_CHANGE,
        actor_type=ActorType.AI_AGENT,
        subject=f"Stage → {stage.name}",
        meta={
            "from_stage_id": str(previous_stage_id) if previous_stage_id else None,
            "to_stage_id": str(stage.id),
            "to_stage_name": stage.name,
        },
    )
    db.add(activity)
    await db.flush()
    return {"deal_id": str(deal.id), "stage_id": str(stage.id), "stage_name": stage.name}


# --- dispatch table ---------------------------------------------------------


ACTION_HANDLERS: dict[str, Any] = {
    "send_email": action_send_email,
    "send_sms": action_send_sms,
    "create_task": action_create_task,
    "assign_owner": action_assign_owner,
    "update_field": action_update_field,
    "add_tag": action_add_tag,
    "notify_user": action_notify_user,
    "wait": action_wait,
    "human_gate": action_human_gate,
    "trigger_agent": action_trigger_agent,
    "create_activity": action_create_activity,
    "change_deal_stage": action_change_deal_stage,
}


def compute_execute_at(delay_minutes: int) -> datetime:
    """Schedule helper used by the engine when materialising step runs."""
    return datetime.now(UTC) + timedelta(minutes=max(delay_minutes, 0))
