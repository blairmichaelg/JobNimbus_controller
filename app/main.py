"""
FastAPI application entrypoint.

Sets up the application with:
- Lifespan context manager for startup/shutdown resource management
- Structured JSON logging via structlog
- Health check endpoint
- Webhook router mount
"""

import logging
import sys
from contextlib import asynccontextmanager

import structlog
from arq import create_pool
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.webhooks import router as webhook_router
from app.api.field_routes import router as field_router
from app.config import get_settings
from app.core.cache import init_db
from app.services.jobnimbus_client import JobNimbusClient
import os


def configure_logging(log_level: str) -> None:
    """Configure structlog for JSON-structured logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            # Use JSON in production, pretty console in development
            (
                structlog.dev.ConsoleRenderer()
                if get_settings().app_env == "development"
                else structlog.processors.JSONRenderer()
            ),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set root logging level
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level, logging.DEBUG),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application startup and shutdown lifecycle.

    Startup:
    - Validate configuration (fail fast on missing env vars)
    - Initialize shared resources (httpx client, Redis pool)

    Shutdown:
    - Cleanly close connections
    """
    logger = structlog.get_logger("app.lifespan")

    # --- Startup ---
    settings = get_settings()
    configure_logging(settings.log_level)

    logger.info(
        "application_starting",
        env=settings.app_env,
        dry_run=settings.dry_run,
        quarantine_status=settings.quarantine_status,
    )

    # Initialize the shared JobNimbus API client (Phase 2)
    jn_client = JobNimbusClient(settings)
    app.state.jn_client = jn_client
    logger.info("jobnimbus_client_attached_to_app_state")

    # Initialize V3 Cache and Directories (Epic 1 & 2)
    init_db()
    os.makedirs("field_photos", exist_ok=True)
    os.makedirs("signed_agreements", exist_ok=True)
    logger.info("v3_infrastructure_initialized")

    # Initialize the ARQ Redis pool for task enqueueing (Phase 3)
    from app.workers.settings import get_redis_settings

    redis_pool = await create_pool(get_redis_settings())
    app.state.redis_pool = redis_pool
    logger.info("arq_redis_pool_attached_to_app_state")

    logger.info("application_ready")

    yield

    # --- Shutdown ---
    logger.info("application_shutting_down")

    # Close the JobNimbus API client (Phase 2)
    if hasattr(app.state, "jn_client"):
        await app.state.jn_client.close()

    # Close the ARQ Redis pool (Phase 3)
    if hasattr(app.state, "redis_pool"):
        await app.state.redis_pool.close()

    logger.info("application_stopped")


app = FastAPI(
    title="Wickham Roofing AI Orchestrator",
    description="Async middleware bridging JobNimbus CRM and Google Gemini AI.",
    version="0.1.0",
    lifespan=lifespan,
)

# --- Middleware ---
class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type or "application/javascript" in content_type:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheMiddleware)

# --- Static & Templates ---
os.makedirs("app/static", exist_ok=True)
os.makedirs("app/templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- Mount Routers ---
app.include_router(webhook_router)
app.include_router(field_router)


# --- Health Check ---
@app.get("/health", tags=["system"])
async def health_check():
    """
    Basic health check endpoint.

    Returns service status. Used by Render for health monitoring
    and to prevent premature instance spin-down.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "env": settings.app_env,
        "dry_run": settings.dry_run,
    }


# --- Frontend ---
@app.get("/app", tags=["frontend"])
async def serve_frontend(request: Request):
    """Serve the Truck Server mobile web interface."""
    return templates.TemplateResponse("field_app.html", {"request": request})
