"""Lead scoring agent — scores a lead 0-100 with full Postgres context."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.activity import Activity, ActivityType, ActorType
from app.models.agent_run import AgentType
from app.models.company import Company
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.lead_score_history import LeadScoreHistory

SYSTEM_PROMPT = (
    "You are a B2B lead scoring expert. Score this lead 0-100 based on:\n"
    "- fit (company size, industry, title)\n"
    "- engagement (email opens, calls, recency)\n"
    "- intent signals (page visits, form fills, inbound vs outbound).\n"
    'Return JSON only with shape: {"score": int, "rationale": str,'
    ' "recommended_action": str, "score_factors": {"fit": int, "engagement": int,'
    ' "intent": int}}'
)


class LeadScorerAgent(BaseAgent):
    agent_type = AgentType.LEAD_SCORER
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
            raise ValueError("lead_scorer requires entity_id (lead_id)")

        lead = (
            await db.execute(
                select(Lead).where(
                    Lead.id == entity_id, Lead.workspace_id == workspace_id
                )
            )
        ).scalar_one_or_none()
        if lead is None:
            raise ValueError(f"lead {entity_id} not found in workspace {workspace_id}")

        contact = (
            await db.execute(select(Contact).where(Contact.id == lead.contact_id))
        ).scalar_one_or_none()
        if contact is None:
            raise ValueError(f"contact {lead.contact_id} not found")

        company = None
        if contact.company_id is not None:
            company = (
                await db.execute(
                    select(Company).where(Company.id == contact.company_id)
                )
            ).scalar_one_or_none()

        activities_rows = (
            await db.execute(
                select(Activity)
                .where(
                    Activity.contact_id == contact.id,
                    Activity.workspace_id == workspace_id,
                )
                .order_by(Activity.occurred_at.desc())
                .limit(20)
            )
        ).scalars().all()
        activities = list(reversed(activities_rows))

        context = {
            "contact": {
                "name": " ".join(
                    p for p in [contact.first_name, contact.last_name] if p
                ),
                "email": contact.email,
                "title": contact.title,
                "source": contact.source,
                "source_campaign": contact.source_campaign,
                "first_seen_at": contact.first_seen_at.isoformat()
                if contact.first_seen_at
                else None,
            },
            "company": (
                {
                    "name": company.name,
                    "domain": company.domain,
                    "industry": company.industry,
                    "employee_count": company.employee_count,
                    "annual_revenue_cents": company.annual_revenue_cents,
                }
                if company
                else None
            ),
            "activities": [
                {
                    "type": a.type.value,
                    "subject": a.subject,
                    "body": (a.body or "")[:500],
                    "occurred_at": a.occurred_at.isoformat(),
                }
                for a in activities
            ],
            "previous_score": lead.score,
            "previous_score_rationale": lead.score_rationale,
        }

        mock = {
            "score": 50,
            "rationale": "Mock scoring response — ANTHROPIC_API_KEY not configured.",
            "recommended_action": "Follow up via email within 48h.",
            "score_factors": {"fit": 50, "engagement": 50, "intent": 50},
        }
        parsed, in_tok, out_tok = await self._call_claude(
            system=SYSTEM_PROMPT,
            user=json.dumps(context, default=str),
            max_tokens=512,
            mock_output=mock,
        )

        score_raw = parsed.get("score", 0)
        try:
            score = max(0, min(100, int(score_raw)))
        except (TypeError, ValueError):
            score = 0
        rationale = str(parsed.get("rationale", ""))

        lead.score = score
        lead.score_rationale = rationale

        db.add(
            Activity(
                workspace_id=workspace_id,
                contact_id=contact.id,
                lead_id=lead.id,
                actor_type=ActorType.AI_AGENT,
                type=ActivityType.SCORE_UPDATE,
                subject=f"Lead score updated to {score}",
                body=rationale,
                meta={"agent_run_id": str(run_id), "score": score},
            )
        )

        db.add(
            LeadScoreHistory(
                workspace_id=workspace_id,
                lead_id=lead.id,
                contact_id=contact.id,
                score=score,
                score_rationale=rationale,
                agent_run_id=run_id,
            )
        )

        return parsed, in_tok, out_tok
