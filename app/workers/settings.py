"""
ARQ worker settings.

Replaces Celery/RQ configuration with ARQ — an async-native task queue
that is dramatically lighter on Redis command usage (critical for
managed Redis services with per-command billing).

This module defines the WorkerSettings class that ARQ uses to
discover tasks, configure Redis connections, and set job defaults.
"""

import structlog
from arq.connections import RedisSettings

from app.config import get_settings
from app.services.jobnimbus_client import JobNimbusClient

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
        )
    else:
        # Standard connection (Render internal KV, local dev)
        from urllib.parse import urlparse

        parsed = urlparse(url)
        parsed = urlparse(url)
        return RedisSettings(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            password=parsed.password,
        )


async def startup(ctx: dict) -> None:
    """
    ARQ worker startup hook.

    Initializes shared resources (like the JobNimbus API client) and
    injects them into the worker context so tasks can use them.
    """
    logger.info("worker_starting_up")
    settings = get_settings()
    jn_client = JobNimbusClient(settings)
    ctx["jn_client"] = jn_client
    logger.info("worker_injected_jobnimbus_client")


async def shutdown(ctx: dict) -> None:
    """
    ARQ worker shutdown hook.

    Cleanly closes shared resources to prevent resource leaks.
    """
    logger.info("worker_shutting_down")
    jn_client: JobNimbusClient | None = ctx.get("jn_client")
    if jn_client:
        await jn_client.close()
    logger.info("worker_stopped")


class WorkerSettings:
    """
    ARQ worker configuration.

    ARQ discovers this class by name when started via:
        arq app.workers.settings.WorkerSettings
    """

    # Task functions registered with the worker
    # ARQ matches enqueued job names to these function references
    functions = [
        "app.workers.job_processor.process_jobnimbus_event",
    ]

    # Redis connection
    redis_settings = get_redis_settings()

    # Job defaults
    max_jobs = 10  # Max concurrent jobs per worker
    job_timeout = 300  # 5 minutes per job
    max_tries = 3  # Retry failed jobs up to 3 times
    health_check_interval = 60  # Seconds between health check pings

    # Lifecycle hooks
    on_startup = startup
    on_shutdown = shutdown
