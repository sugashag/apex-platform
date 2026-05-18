"""Thin async wrapper around the Anthropic SDK.

When `ANTHROPIC_API_KEY` is not set the service runs in mock mode: callers
get back the JSON-serialized `mock_output` they supplied along with synthetic
token counts. This keeps CI runnable without a real key while keeping the
production path identical at the call site.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class AnthropicService:
    """Returns (text, input_tokens, output_tokens). Mock-mode safe."""

    def __init__(self) -> None:
        self._configured = bool(settings.ANTHROPIC_API_KEY)
        self._client: Any | None = None
        if self._configured:
            try:
                from anthropic import AsyncAnthropic

                self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            except ImportError:
                logger.warning(
                    "anthropic package not installed; AnthropicService running in mock mode"
                )
                self._configured = False

    @property
    def configured(self) -> bool:
        return self._configured

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 1024,
        mock_output: dict[str, Any] | None = None,
    ) -> tuple[str, int, int]:
        """Run a single-turn Claude completion.

        Returns (response_text, input_tokens, output_tokens).
        In mock mode returns `json.dumps(mock_output)` with synthetic token counts
        so callers that expect JSON parse cleanly.
        """
        if not self._configured or self._client is None:
            payload = mock_output if mock_output is not None else {"mock": True}
            text = json.dumps({**payload, "_mock": True})
            return text, max(1, len(system) // 4 + len(user) // 4), max(1, len(text) // 4)

        try:
            response = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:
            logger.exception("anthropic API call failed")
            raise RuntimeError(f"Anthropic API call failed: {exc}") from exc

        text_parts: list[str] = []
        for block in response.content:
            text_value = getattr(block, "text", None)
            if text_value:
                text_parts.append(text_value)
        text = "".join(text_parts)
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return text, input_tokens, output_tokens


anthropic_service = AnthropicService()
