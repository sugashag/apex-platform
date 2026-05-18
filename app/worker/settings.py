"""ARQ worker settings — entry point for `arq app.worker.settings.WorkerSettings`."""

from __future__ import annotations

from arq.connections import RedisSettings
from arq.cron import cron

from app.config import settings
from app.worker.jobs import (
    check_sla_breaches,
    execute_workflow_step,
    process_sequences,
    process_workflow_step_queue,
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
        execute_workflow_step,
        process_sequences,
        process_workflow_step_queue,
        check_sla_breaches,
    ]
    # Cron jobs: SLA every 5 minutes, sequences every 15, workflow catch-up
    # every minute so delayed steps fire on time without per-step Redis
    # roundtrips at trigger time.
    cron_jobs = [
        cron(check_sla_breaches, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        cron(process_sequences, minute={0, 15, 30, 45}),
        cron(process_workflow_step_queue, minute=set(range(0, 60))),
    ]
    max_jobs = settings.WORKER_MAX_JOBS
    job_timeout = settings.WORKER_JOB_TIMEOUT
