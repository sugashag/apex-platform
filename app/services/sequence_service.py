"""Sequence enrollment + due-step processing.

Sequences are an opinionated subset of workflows: they send a series of
templated emails/SMS to a contact, advance one step per tick, and stop
when the contact replies (if ``exit_on_reply`` is set).

The cron poller calls ``process_due_steps`` periodically; webhooks/email
ingest calls ``exit_on_reply`` whenever an inbound message lands.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.activity import Activity, ActivityType, ActorType
from app.models.contact import Contact
from app.models.sequence import Sequence
from app.models.sequence_enrollment import (
    SequenceEnrollment,
    SequenceEnrollmentStatus,
)
from app.models.sequence_step import SequenceStep, SequenceStepType
from app.models.thread import Thread
from app.services.email_service import email_service
from app.services.template_service import render_template
from app.services.twilio_service import twilio_service

logger = logging.getLogger(__name__)


async def _load_steps(
    db: AsyncSession, sequence_id: UUID
) -> list[SequenceStep]:
    result = await db.execute(
        select(SequenceStep)
        .where(SequenceStep.sequence_id == sequence_id)
        .order_by(SequenceStep.position.asc())
    )
    return list(result.scalars().all())


async def enroll_contact(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    sequence_id: UUID,
    contact_id: UUID,
    deal_id: UUID | None = None,
    enrolled_by_id: UUID | None = None,
) -> SequenceEnrollment:
    """Enroll a contact in a sequence.

    Raises ValueError if:
      - sequence doesn't belong to the workspace
      - contact already has an active enrollment in this sequence
    Caller commits.
    """
    seq_result = await db.execute(
        select(Sequence).where(
            Sequence.id == sequence_id,
            Sequence.workspace_id == workspace_id,
        )
    )
    sequence = seq_result.scalar_one_or_none()
    if sequence is None:
        raise ValueError("sequence not in this workspace")

    existing_result = await db.execute(
        select(SequenceEnrollment).where(
            SequenceEnrollment.sequence_id == sequence_id,
            SequenceEnrollment.contact_id == contact_id,
            SequenceEnrollment.status == SequenceEnrollmentStatus.ACTIVE,
        )
    )
    if existing_result.scalar_one_or_none() is not None:
        raise ValueError("contact already enrolled in this sequence")

    steps = await _load_steps(db, sequence_id)
    next_step_at: datetime | None = None
    if steps:
        delay = max(steps[0].delay_days, 0)
        next_step_at = datetime.now(UTC) + timedelta(days=delay)

    enrollment = SequenceEnrollment(
        workspace_id=workspace_id,
        sequence_id=sequence_id,
        contact_id=contact_id,
        deal_id=deal_id,
        enrolled_by_id=enrolled_by_id,
        status=(
            SequenceEnrollmentStatus.ACTIVE
            if steps
            else SequenceEnrollmentStatus.COMPLETED
        ),
        current_step=0,
        next_step_at=next_step_at,
    )
    if not steps:
        enrollment.exited_at = datetime.now(UTC)
    db.add(enrollment)
    await db.flush()
    return enrollment


def _build_context(contact: Contact) -> dict[str, object]:
    return {
        "contact": {
            "id": str(contact.id),
            "email": contact.email,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "phone": contact.phone,
            "title": contact.title,
        },
    }


async def _execute_step(
    db: AsyncSession,
    enrollment: SequenceEnrollment,
    step: SequenceStep,
    contact: Contact,
) -> None:
    """Run the user-visible side effect of a single sequence step."""
    context = _build_context(contact)
    subject = render_template(step.subject_template, context) or "(no subject)"
    body = render_template(step.body_template, context)

    if step.step_type in (SequenceStepType.EMAIL, SequenceStepType.AI_DRAFT_EMAIL):
        if not contact.email:
            logger.info(
                "sequence %s step %s: contact %s has no email — skipping",
                enrollment.sequence_id,
                step.position,
                contact.id,
            )
            return
        thread = Thread(
            workspace_id=enrollment.workspace_id,
            contact_id=contact.id,
            deal_id=enrollment.deal_id,
            subject=subject,
        )
        db.add(thread)
        await db.flush()
        await email_service.send_message(
            db,
            thread,
            body_text=body or None,
            body_html=None,
            from_account=None,
            actor_id=enrollment.enrolled_by_id,
            to_emails=[contact.email],
        )
        return

    if step.step_type == SequenceStepType.SMS:
        if not contact.phone:
            logger.info(
                "sequence %s step %s: contact %s has no phone — skipping",
                enrollment.sequence_id,
                step.position,
                contact.id,
            )
            return
        from_number = settings.TWILIO_FROM_NUMBER or "+15555555555"
        await twilio_service.send_sms(contact.phone, from_number, body)
        return

    if step.step_type == SequenceStepType.CALL_TASK:
        activity = Activity(
            workspace_id=enrollment.workspace_id,
            contact_id=contact.id,
            deal_id=enrollment.deal_id,
            actor_id=enrollment.enrolled_by_id,
            type=ActivityType.TASK,
            actor_type=ActorType.AI_AGENT,
            subject=subject,
            body=body or None,
            meta={"sequence_id": str(enrollment.sequence_id), "step": step.position},
        )
        db.add(activity)
        await db.flush()
        return


async def process_due_steps(
    db: AsyncSession, workspace_id: UUID | None = None
) -> int:
    """Find every active enrollment whose next_step_at is due, run its
    current step, advance the cursor. Returns the count of steps processed.

    If ``workspace_id`` is provided, only that workspace's enrollments are
    processed (useful for per-workspace cron schedules).
    """
    now = datetime.now(UTC)

    conditions = [
        SequenceEnrollment.status == SequenceEnrollmentStatus.ACTIVE,
        SequenceEnrollment.next_step_at.is_not(None),
        SequenceEnrollment.next_step_at <= now,
    ]
    if workspace_id is not None:
        conditions.append(SequenceEnrollment.workspace_id == workspace_id)

    result = await db.execute(
        select(SequenceEnrollment).where(and_(*conditions))
    )
    enrollments = list(result.scalars().all())

    processed = 0
    for enrollment in enrollments:
        step_result = await db.execute(
            select(SequenceStep)
            .where(
                SequenceStep.sequence_id == enrollment.sequence_id,
                SequenceStep.position == enrollment.current_step,
            )
            .limit(1)
        )
        step = step_result.scalar_one_or_none()
        if step is None:
            enrollment.status = SequenceEnrollmentStatus.COMPLETED
            enrollment.next_step_at = None
            enrollment.exited_at = now
            continue

        contact = await db.get(Contact, enrollment.contact_id)
        if contact is None:
            enrollment.status = SequenceEnrollmentStatus.EXITED_MANUAL
            enrollment.next_step_at = None
            enrollment.exited_at = now
            continue

        try:
            await _execute_step(db, enrollment, step, contact)
        except Exception:  # noqa: BLE001
            logger.exception(
                "sequence step %s failed for enrollment %s",
                step.position,
                enrollment.id,
            )

        next_step_result = await db.execute(
            select(SequenceStep)
            .where(
                SequenceStep.sequence_id == enrollment.sequence_id,
                SequenceStep.position > step.position,
            )
            .order_by(SequenceStep.position.asc())
            .limit(1)
        )
        next_step = next_step_result.scalar_one_or_none()

        if next_step is None:
            enrollment.status = SequenceEnrollmentStatus.COMPLETED
            enrollment.next_step_at = None
            enrollment.exited_at = datetime.now(UTC)
        else:
            enrollment.current_step = next_step.position
            enrollment.next_step_at = datetime.now(UTC) + timedelta(
                days=max(next_step.delay_days, 0)
            )

        processed += 1

    await db.flush()
    return processed


async def exit_on_reply(db: AsyncSession, contact_id: UUID) -> int:
    """Stop every active enrollment whose sequence has exit_on_reply=True.

    Returns the count exited. Caller commits.
    """
    result = await db.execute(
        select(SequenceEnrollment, Sequence)
        .join(Sequence, Sequence.id == SequenceEnrollment.sequence_id)
        .where(
            SequenceEnrollment.contact_id == contact_id,
            SequenceEnrollment.status == SequenceEnrollmentStatus.ACTIVE,
            Sequence.exit_on_reply.is_(True),
        )
    )
    rows = list(result.all())
    now = datetime.now(UTC)
    for enrollment, _ in rows:
        enrollment.status = SequenceEnrollmentStatus.EXITED_REPLY
        enrollment.next_step_at = None
        enrollment.exited_at = now
    await db.flush()
    return len(rows)


async def exit_enrollment(
    db: AsyncSession, enrollment_id: UUID
) -> SequenceEnrollment | None:
    """Manual exit. Caller commits."""
    enrollment = await db.get(SequenceEnrollment, enrollment_id)
    if enrollment is None:
        return None
    if enrollment.status != SequenceEnrollmentStatus.ACTIVE:
        return enrollment
    enrollment.status = SequenceEnrollmentStatus.EXITED_MANUAL
    enrollment.next_step_at = None
    enrollment.exited_at = datetime.now(UTC)
    await db.flush()
    return enrollment
