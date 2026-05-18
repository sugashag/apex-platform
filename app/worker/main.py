"""Convenience entry point: `python -m app.worker.main`.

Production deploys can either use ``arq app.worker.settings.WorkerSettings``
directly or invoke this module — the two are equivalent.
"""

from __future__ import annotations

from typing import Any, cast

from arq.worker import run_worker

from app.worker.settings import WorkerSettings


def main() -> None:
    # ARQ's WorkerSettings is a plain class with a known protocol — its
    # WorkerSettingsBase TypeVar makes the strict mypy check overly tight.
    run_worker(cast(Any, WorkerSettings))


if __name__ == "__main__":
    main()
