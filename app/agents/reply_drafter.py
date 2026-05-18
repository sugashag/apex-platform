"""Reply drafter — drafts a reply to an inbound email thread."""

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
from app.models.deal import Deal
from app.models.message import Message
from app.models.thread import Thread

SYSTEM_PROMPT = (
    "You are a professional B2B account executive drafting a reply to a customer email. "
    "Match the customer's tone, address their points directly, and end with a clear next step. "
    'Return JSON only with shape: {"body_html": str, "body_text": str,'
    ' "suggested_action": "reply"|"escalate"|"close", "confidence": float}'
)


class ReplyDrafterAgent(BaseAgent):
    agent_type = AgentType.REPLY_DRAFTER
    model = "claude-sonnet-4-6"

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
            raise ValueError("reply_drafter requires entity_id (thread_id)")

        thread = (
            await db.execute(
                select(Thread).where(
                    Thread.id == entity_id, Thread.workspace_id == workspace_id
                )
            )
        ).scalar_one_or_none()
        if thread is None:
            raise ValueError(
                f"thread {entity_id} not found in workspace {workspace_id}"
            )

        messages = list(
            (
                await db.execute(
                    select(Message)
                    .where(Message.thread_id == thread.id)
                    .order_by(Message.sent_at.asc())
                )
            ).scalars().all()
        )

        contact: Contact | None = None
        company: Company | None = None
        if thread.contact_id is not None:
            contact = (
                await db.execute(
                    select(Contact).where(Contact.id == thread.contact_id)
                )
            ).scalar_one_or_none()
            if contact and contact.company_id is not None:
                company = (
                    await db.execute(
                        select(Company).where(Company.id == contact.company_id)
                    )
                ).scalar_one_or_none()

        deal: Deal | None = None
        if thread.deal_id is not None:
            deal = (
                await db.execute(select(Deal).where(Deal.id == thread.deal_id))
            ).scalar_one_or_none()

        context = {
            "thread_subject": thread.subject,
            "messages": [
                {
                    "direction": m.direction.value,
                    "from": m.from_email,
                    "body": (m.body_text or m.body_html or "")[:2000],
                    "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                }
                for m in messages
            ],
            "contact": (
                {
                    "name": " ".join(
                        p for p in [contact.first_name, contact.last_name] if p
                    ),
                    "title": contact.title,
                    "email": contact.email,
                }
                if contact
                else None
            ),
            "company": (
                {"name": company.name, "industry": company.industry}
                if company
                else None
            ),
            "deal": {"name": deal.name} if deal else None,
        }

        mock = {
            "body_html": "<p>Mock reply draft.</p>",
            "body_text": "Mock reply draft.",
            "suggested_action": "reply",
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
                draft_type=AiDraftType.EMAIL_REPLY,
                entity_type="thread",
                entity_id=thread.id,
                subject=thread.subject,
                body_html=parsed.get("body_html"),
                body_text=parsed.get("body_text"),
                status=AiDraftStatus.PENDING,
            )
        )

        return parsed, in_tok, out_tok
