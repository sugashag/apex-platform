"""Objection handler — proposes reframes for objections surfaced on a call."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.activity import Activity, ActivityType, ActorType
from app.models.agent_run import AgentType
from app.models.call import Call
from app.models.contact import Contact
from app.models.deal import Deal

SYSTEM_PROMPT = (
    "You are an expert B2B sales coach. Given the objections raised on a sales call, "
    "propose evidence-backed reframes and a concrete follow-up. "
    'Return JSON only with shape: {"objections": [{"objection": str, "reframe": str,'
    ' "evidence_points": [str], "suggested_follow_up": str}]}'
)


class ObjectionHandlerAgent(BaseAgent):
    agent_type = AgentType.OBJECTION_HANDLER
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
            raise ValueError("objection_handler requires entity_id (call_id)")

        call = (
            await db.execute(
                select(Call).where(
                    Call.id == entity_id, Call.workspace_id == workspace_id
                )
            )
        ).scalar_one_or_none()
        if call is None:
            raise ValueError(f"call {entity_id} not found in workspace {workspace_id}")

        objections: list[str] = kwargs.get("objections") or []
        if not objections:
            raise ValueError("objection_handler requires non-empty `objections` kwarg")

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

        prior_calls = []
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
            "objections": objections,
            "contact": (
                {"name": " ".join(p for p in [contact.first_name, contact.last_name] if p),
                 "title": contact.title}
                if contact
                else None
            ),
            "deal_stage_id": (
                str(deal.pipeline_stage_id)
                if deal and deal.pipeline_stage_id
                else None
            ),
            "previous_call_summaries": [c.ai_summary for c in prior_calls],
        }

        mock = {
            "objections": [
                {
                    "objection": o,
                    "reframe": "Mock reframe (no ANTHROPIC_API_KEY).",
                    "evidence_points": ["mock"],
                    "suggested_follow_up": "Schedule follow-up call.",
                }
                for o in objections
            ]
        }
        parsed, in_tok, out_tok = await self._call_claude(
            system=SYSTEM_PROMPT,
            user=json.dumps(context, default=str),
            max_tokens=1024,
            mock_output=mock,
        )

        formatted = _format_objections(parsed.get("objections") or [])

        if call.contact_id is not None:
            db.add(
                Activity(
                    workspace_id=workspace_id,
                    contact_id=call.contact_id,
                    deal_id=call.deal_id,
                    actor_type=ActorType.AI_AGENT,
                    type=ActivityType.NOTE,
                    subject="AI: objection handling suggestions",
                    body=formatted,
                    meta={"agent_run_id": str(run_id), "call_id": str(call.id)},
                )
            )

        return parsed, in_tok, out_tok


def _format_objections(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        lines.append(f"Objection: {item.get('objection', '').strip()}")
        if reframe := item.get("reframe"):
            lines.append(f"Reframe: {reframe}")
        evidence = item.get("evidence_points") or []
        if evidence:
            lines.append("Evidence:")
            for ev in evidence:
                lines.append(f"  - {ev}")
        if follow := item.get("suggested_follow_up"):
            lines.append(f"Follow up: {follow}")
        lines.append("")
    return "\n".join(lines).strip()
