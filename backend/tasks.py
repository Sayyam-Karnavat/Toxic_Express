"""Enqueue background jobs (executed by worker.py). Jobs are idempotent and retried by arq."""

import logging
from datetime import timedelta
from typing import Any

from config import settings

logger = logging.getLogger(__name__)


async def enqueue(
    job: str,
    *args: Any,
    job_id: str | None = None,
    defer_seconds: float | None = None,
) -> None:
    if settings.tasks_eager:
        # Test mode: run the job inline so request -> job -> result is observable synchronously.
        import worker

        await worker.JOBS[job]({"job_try": 1, "eager": True}, *args)
        return

    from cache import get_redis

    await get_redis().enqueue_job(
        job,
        *args,
        _job_id=job_id,
        _defer_by=timedelta(seconds=defer_seconds) if defer_seconds else None,
    )
    logger.debug("enqueued %s (%s)", job, job_id)
