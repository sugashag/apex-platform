"""Outbound email drafter — writes a personalized first-touch email."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.agent_run import AgentType
from app.models.ai_draft import AiDraft, AiDraftStatus, AiDraftType
from app.models.company import Company
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.message import Message, MessageDirection
from app.models.thread import Thread

SYSTEM_PROMPT = (
    "You are an expert B2B sales copywriter. Write a personalized outbound email. "
    "Never use generic openers. Reference specific signals about the prospect. "
    "Be concise and end with one clear CTA. "
    'Return JSON only with shape: {"subject": str, "body_html": str,'
    ' "body_text": str, "confidence": float}'
)


class OutboundDrafterAgent(BaseAgent):
    agent_type = AgentType.OUTBOUND_DRAFTER
    model = "claude-opus-4-6"

    async def _perform(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        workspace_id: UUID,
        entity_id: UUID | None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], int, int]:
        if entity_id is None:
            raise ValueError("outbound_drafter requires entity_id (contact_id)")

        contact = (
            await db.execute(
                select(Contact).where(
                    Contact.id == entity_id, Contact.workspace_id == workspace_id
                )
            )
        ).scalar_one_or_none()
        if contact is None:
            raise ValueError(
                f"contact {entity_id} not found in workspace {workspace_id}"
            )

        company = None
        if contact.company_id is not None:
            company = (
                await db.execute(
                    select(Company).where(Company.id == contact.company_id)
                )
            ).scalar_one_or_none()

        lead = (
            await db.execute(
                select(Lead)
                .where(
                    Lead.workspace_id == workspace_id,
                    Lead.contact_id == contact.id,
                )
                .order_by(Lead.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        previous_messages = list(
            (
                await db.execute(
                    select(Message)
                    .join(Thread, Thread.id == Message.thread_id)
                    .where(
                        Message.workspace_id == workspace_id,
                        Thread.contact_id == contact.id,
                        Message.direction == MessageDirection.OUTBOUND,
                    )
                    .order_by(Message.sent_at.desc())
                    .limit(5)
                )
            ).scalars().all()
        )

        step_instructions = kwargs.get("step_instructions") or (
            "First touch, keep under 100 words, one clear CTA."
        )

        context = {
            "contact": {
                "name": " ".join(
                    p for p in [contact.first_name, contact.last_name] if p
                ),
                "email": contact.email,
                "title": contact.title,
                "source": contact.source,
                "source_campaign": contact.source_campaign,
            },
            "company": (
                {
                    "name": company.name,
                    "domain": company.domain,
                    "industry": company.industry,
                    "employee_count": company.employee_count,
                }
                if company
                else None
            ),
            "lead_score": lead.score if lead else None,
            "lead_score_rationale": lead.score_rationale if lead else None,
            "previous_outreach": [
                {
                    "subject": m.body_text and m.body_text[:80],
                    "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                }
                for m in previous_messages
            ],
            "step_instructions": step_instructions,
        }

        mock = {
            "subject": f"Quick question about {company.name if company else 'your team'}",
            "body_html": "<p>Hi — mock draft generated without ANTHROPIC_API_KEY.</p>",
            "body_text": "Hi — mock draft generated without ANTHROPIC_API_KEY.",
            "confidence": 0.5,
        }
        parsed, in_tok, out_tok = await self._call_claude(
            system=SYSTEM_PROMPT,
            user=json.dumps(context, default=str),
            max_tokens=1024,
            mock_output=mock,
        )

        db.add(
            AiDraft(
                workspace_id=workspace_id,
                agent_run_id=run_id,
                draft_type=AiDraftType.OUTBOUND_EMAIL,
                entity_type="contact",
                entity_id=contact.id,
                subject=str(parsed.get("subject") or "")[:500] or None,
                body_html=parsed.get("body_html"),
                body_text=parsed.get("body_text"),
                status=AiDraftStatus.PENDING,
            )
        )

        return parsed, in_tok, out_tok
