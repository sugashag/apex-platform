"""BaseAgent — shared lifecycle for every Claude-powered agent.

The AgentRun audit record lives in its own dedicated session so it survives
caller rollbacks (e.g. FastAPI's `get_session` rolls back on exception, and
ARQ job functions don't commit when their callable raises). Side effects
like updating a lead score or creating an AiDraft go on the caller's session
and follow the caller's commit/rollback policy.

Subclasses set ``agent_type`` + ``model`` and implement ``_perform``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.models.agent_run import AgentRun, AgentRunStatus, AgentType
from app.services.anthropic_service import anthropic_service

logger = logging.getLogger(__name__)


class BaseAgent:
    """Abstract base class — subclass must set `agent_type` and implement `_perform`."""

    agent_type: AgentType
    model: str = "claude-opus-4-6"

    async def execute(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID,
        entity_id: UUID | None,
        entity_type: str | None,
        trigger: str,
        **kwargs: Any,
    ) -> AgentRun:
        """Run the agent end-to-end with durable audit logging.

        Returns the AgentRun (loaded into the caller's session for convenience).
        Side effects are written to the caller's session — caller commits.
        """
        run_id = await self._create_run(
            workspace_id=workspace_id,
            entity_id=entity_id,
            entity_type=entity_type,
            trigger=trigger,
        )

        started = time.perf_counter()
        try:
            output, input_tokens, output_tokens = await self._perform(
                db,
                run_id=run_id,
                workspace_id=workspace_id,
                entity_id=entity_id,
                **kwargs,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            await self._finish_run(
                run_id,
                status=AgentRunStatus.FAILED,
                error_message=f"{type(exc).__name__}: {exc}",
                latency_ms=latency_ms,
            )
            logger.exception("agent %s failed", self.agent_type.value)
            raise

        latency_ms = int((time.perf_counter() - started) * 1000)
        await self._finish_run(
            run_id,
            status=AgentRunStatus.COMPLETED,
            output=output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

        # Load into caller's session for convenient return-value access.
        run = await db.get(AgentRun, run_id)
        if run is None:  # pragma: no cover — defensive
            raise RuntimeError(f"agent run {run_id} disappeared")
        await db.refresh(run)
        return run

    async def _perform(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        workspace_id: UUID,
        entity_id: UUID | None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], int, int]:
        """Subclasses implement. Returns (output_dict, input_tokens, output_tokens).

        Subclasses should perform side effects (update entity, create activities,
        create drafts, etc.) inside this method using the provided session.
        """
        raise NotImplementedError

    async def _call_claude(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
        mock_output: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int, int]:
        """Call Claude and parse JSON output.

        Returns (parsed_json, input_tokens, output_tokens). Raises ValueError
        if the response is not valid JSON.
        """
        text, input_tokens, output_tokens = await anthropic_service.complete(
            system=system,
            user=user,
            model=self.model,
            max_tokens=max_tokens,
            mock_output=mock_output,
        )
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Claude returned non-JSON response: {text[:200]}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError("Claude returned non-object JSON")
        return parsed, input_tokens, output_tokens

    async def _create_run(
        self,
        *,
        workspace_id: UUID,
        entity_id: UUID | None,
        entity_type: str | None,
        trigger: str,
    ) -> UUID:
        async with SessionLocal() as audit_db:
            run = AgentRun(
                workspace_id=workspace_id,
                agent_type=self.agent_type,
                trigger=trigger,
                entity_type=entity_type,
                entity_id=entity_id,
                status=AgentRunStatus.RUNNING,
                model_used=self.model,
            )
            audit_db.add(run)
            await audit_db.commit()
            await audit_db.refresh(run)
            return run.id

    async def _finish_run(
        self,
        run_id: UUID,
        *,
        status: AgentRunStatus,
        output: dict[str, Any] | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        async with SessionLocal() as audit_db:
            run = await audit_db.get(AgentRun, run_id)
            if run is None:  # pragma: no cover — defensive
                return
            run.status = status
            if output is not None:
                run.output = output
            if input_tokens is not None:
                run.input_tokens = input_tokens
            if output_tokens is not None:
                run.output_tokens = output_tokens
            if latency_ms is not None:
                run.latency_ms = latency_ms
            if error_message is not None:
                run.error_message = error_message
            await audit_db.commit()
