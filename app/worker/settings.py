"""ARQ worker settings — entry point for `arq app.worker.settings.WorkerSettings`."""

from __future__ import annotations

from arq.connections import RedisSettings

from app.config import settings
from app.worker.jobs import (
    run_call_summarizer,
    run_lead_scorer,
    run_objection_handler,
    run_outbound_drafter,
    run_reply_drafter,
)


class WorkerSettings:
    """ARQ discovers this class from the CLI argument."""

    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [
        run_lead_scorer,
        run_call_summarizer,
        run_outbound_drafter,
        run_reply_drafter,
        run_objection_handler,
    ]
    max_jobs = settings.WORKER_MAX_JOBS
    job_timeout = settings.WORKER_JOB_TIMEOUT
