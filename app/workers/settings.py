"""
ARQ worker settings.

Replaces Celery/RQ configuration with ARQ — an async-native task queue
that is dramatically lighter on Redis command usage (critical for
managed Redis services with per-command billing).

This module defines the WorkerSettings class that ARQ uses to
discover tasks, configure Redis connections, and set job defaults.
"""

import structlog
import asyncio
from arq.connections import RedisSettings
from arq.cron import cron

from app.config import get_settings
from app.core.cleanup import cleanup_orphaned_artifacts
from app.core.backup import backup_database

logger = structlog.get_logger("app.workers.settings")


def get_redis_settings() -> RedisSettings:
    """
    Parse the REDIS_URL into ARQ's RedisSettings object.

    Supports both redis:// and rediss:// (TLS) connection strings.
    """
    settings = get_settings()
    url = settings.redis_url

    # Parse the URL into components for ARQ's RedisSettings
    # ARQ uses its own RedisSettings rather than a raw URL string
    if url.startswith("rediss://"):
        # TLS connection (Upstash, some managed providers)
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return RedisSettings(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6380,
            password=parsed.password,
            ssl=True,
            database=0 if settings.app_env.lower() == "prod" else 1,
        )
    else:
        # Standard connection (Render internal KV, local dev)
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return RedisSettings(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            password=parsed.password,
            database=0 if settings.app_env.lower() == "prod" else 1,
        )


async def startup(ctx: dict) -> None:
    """
    ARQ worker startup hook.
    """
    settings = get_settings()
    if settings.app_env.lower() == "prod":
        logger.info("[PROD MODE] Worker connected to Redis DB 0")
    else:
        logger.info("[DEV MODE] Worker connected to Redis DB 1")
    logger.info("worker_starting_up")


async def shutdown(ctx: dict) -> None:
    """
    ARQ worker shutdown hook.
    """
    logger.info("worker_shutting_down")
    logger.info("worker_stopped")


async def run_cleanup(ctx: dict) -> None:
    """
    Nightly cron job to clean up orphaned temporary files.
    """
    logger.info("cron_cleanup_started")
    await asyncio.to_thread(cleanup_orphaned_artifacts)
    logger.info("cron_cleanup_finished")

async def run_backup(ctx: dict) -> None:
    """
    Cron job to backup the SQLite database safely using the native backup API.
    """
    logger.info("cron_backup_started")
    await asyncio.to_thread(backup_database, 14)
    logger.info("cron_backup_finished")


class WorkerSettings:
    """
    ARQ worker configuration.

    ARQ discovers this class by name when started via:
        arq app.workers.settings.WorkerSettings
    """

    # Task functions registered with the worker
    # ARQ matches enqueued job names to these function references
    functions = [
        "app.workers.supplement_processor.process_supplement_event",
        "app.workers.inspection_processor.process_inspection",
        "app.workers.rebuttal_processor.process_rebuttal",
        "app.workers.retail_quote_processor.process_retail_quote",
    ]

    # Redis connection
    redis_settings = get_redis_settings()

    # Job defaults
    max_jobs = 10  # Max concurrent jobs per worker
    job_timeout = 1800  # 30 minutes per job to support large commercial inspections
    max_tries = 3  # Retry failed jobs up to 3 times
    health_check_interval = 60  # Seconds between health check pings

    # Lifecycle hooks
    on_startup = startup
    on_shutdown = shutdown

    # Cron jobs
    cron_jobs = [
        cron(run_cleanup, hour=2, minute=0),
        cron(run_backup, hour={0, 4, 8, 12, 16, 20}, minute=0)
    ]
