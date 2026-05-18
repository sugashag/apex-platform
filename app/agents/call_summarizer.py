"""Call summarization agent — summarizes a completed call from its transcript."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.activity import Activity, ActivityType, ActorType
from app.models.agent_run import AgentType
from app.models.call import Call, CallSentiment
from app.models.contact import Contact
from app.models.deal import Deal

SYSTEM_PROMPT = (
    "You are an expert sales call analyst. Summarize this call and extract key "
    "information. Return JSON only with shape: "
    '{"summary": str, "key_topics": [str], "sentiment": "positive"|"neutral"|"negative",'
    ' "objections_raised": [str], "next_action": str, "score_delta_signal": bool}'
)


class CallSummarizerAgent(BaseAgent):
    agent_type = AgentType.CALL_SUMMARIZER
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
            raise ValueError("call_summarizer requires entity_id (call_id)")

        call = (
            await db.execute(
                select(Call).where(
                    Call.id == entity_id, Call.workspace_id == workspace_id
                )
            )
        ).scalar_one_or_none()
        if call is None:
            raise ValueError(f"call {entity_id} not found in workspace {workspace_id}")
        if not call.transcript:
            raise ValueError("call has no transcript yet")

        contact: Contact | None = None
        if call.contact_id is not None:
            contact = (
                await db.execute(select(Contact).where(Contact.id == call.contact_id))
            ).scalar_one_or_none()

        deal: Deal | None = None
        if call.deal_id is not None:
            deal = (
                await db.execute(select(Deal).where(Deal.id == call.deal_id))
            ).scalar_one_or_none()

        prior_calls: list[Call] = []
        if contact is not None:
            prior_calls = list(
                (
                    await db.execute(
                        select(Call)
                        .where(
                            Call.workspace_id == workspace_id,
                            Call.contact_id == contact.id,
                            Call.id != call.id,
                            Call.ai_summary.is_not(None),
                        )
                        .order_by(Call.created_at.desc())
                        .limit(3)
                    )
                ).scalars().all()
            )

        context = {
            "transcript": call.transcript,
            "contact": (
                {
                    "name": " ".join(
                        p for p in [contact.first_name, contact.last_name] if p
                    ),
                    "title": contact.title,
                    "source": contact.source,
                }
                if contact
                else None
            ),
            "deal": (
                {
                    "name": deal.name,
                    "stage_id": str(deal.pipeline_stage_id)
                    if deal.pipeline_stage_id
                    else None,
                }
                if deal
                else None
            ),
            "previous_summaries": [c.ai_summary for c in prior_calls],
        }

        mock = {
            "summary": "Mock call summary — ANTHROPIC_API_KEY not configured.",
            "key_topics": ["mock"],
            "sentiment": "neutral",
            "objections_raised": [],
            "next_action": "Send follow-up email.",
            "score_delta_signal": False,
        }
        parsed, in_tok, out_tok = await self._call_claude(
            system=SYSTEM_PROMPT,
            user=json.dumps(context, default=str),
            max_tokens=1024,
            mock_output=mock,
        )

        summary = str(parsed.get("summary", ""))
        next_action = str(parsed.get("next_action", "")) or None
        sentiment_raw = str(parsed.get("sentiment", "")).lower()
        try:
            sentiment = CallSentiment(sentiment_raw) if sentiment_raw else None
        except ValueError:
            sentiment = None

        call.ai_summary = summary
        call.ai_sentiment = sentiment
        call.ai_next_action = next_action

        if call.contact_id is not None:
            db.add(
                Activity(
                    workspace_id=workspace_id,
                    contact_id=call.contact_id,
                    deal_id=call.deal_id,
                    actor_type=ActorType.AI_AGENT,
                    type=ActivityType.CALL,
                    subject="AI call summary",
                    body=summary,
                    meta={"agent_run_id": str(run_id), "call_id": str(call.id)},
                )
            )

        return parsed, in_tok, out_tok
