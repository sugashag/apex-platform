"""Helper for enqueueing background agent jobs onto Redis via ARQ.

Services and webhooks call ``enqueue(...)`` after the originating database
transaction commits. If Redis is unavailable (CI/dev without `redis-server`)
the call is logged and silently no-ops — agent enqueuing is best-effort, and
the human-driven REST endpoints can always re-trigger the same agent.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.config import settings

logger = logging.getLogger(__name__)


async def enqueue(
    job_name: str,
    workspace_id: UUID,
    entity_id: UUID | None,
    **kwargs: Any,
) -> bool:
    """Enqueue an ARQ job. Returns True on success, False if skipped.

    Best-effort: connection or import failures are logged and swallowed.
    """
    try:
        from arq.connections import RedisSettings, create_pool
    except ImportError:
        logger.warning("arq not installed; skipping enqueue for %s", job_name)
        return False

    try:
        pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    except Exception as exc:  # noqa: BLE001 — Redis down should not crash callers
        logger.warning("could not connect to Redis to enqueue %s: %s", job_name, exc)
        return False

    try:
        await pool.enqueue_job(
            job_name,
            str(workspace_id),
            str(entity_id) if entity_id is not None else None,
            **kwargs,
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to enqueue %s", job_name)
        return False
    finally:
        try:
            await pool.close()
        except Exception:  # noqa: BLE001
            logger.debug("ignoring error while closing arq pool", exc_info=True)

    return True
