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
from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.webhooks import router as webhook_router
from app.api.field_routes import router as field_router
from app.api.office_routes import router as office_router, _fetch_job_sync
from app.config import get_settings
from app.core.cache import init_db as init_cache_db
from app.core.database import init_db as init_crm_db, get_connection
import os
import asyncio


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
    
    # Stark visibility for Dev/Prod split
    if settings.app_env.lower() == "prod":
        logger.info("[PROD MODE] Using data/jobnimbus.db on port 8000")
    else:
        logger.info("[DEV MODE] Using data/jobnimbus_dev.db on port 8001")

    # Initialize V3 Cache and Directories (Epic 1 & 2)
    init_cache_db()
    # Initialize V4 CRM DB
    init_crm_db()
    os.makedirs("field_photos", exist_ok=True)
    os.makedirs("data/field_docs", exist_ok=True)
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ],
    allow_origin_regex=r"https://.*\.ngrok-free\.app|https://.*\.trycloudflare\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(office_router)

from app.core.notifications import notifier
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/office")
async def office_ws(websocket: WebSocket):
    # Using generic client_id for now, can be extracted from query params or headers if needed
    await notifier.connect(websocket, client_id="office_client", role="office")
    try:
        while True:
            data = await websocket.receive_text()
            if data == "pong":
                notifier.update_pong(websocket)
    except WebSocketDisconnect:
        notifier.disconnect(websocket)


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
@app.get("/field", tags=["frontend"])
async def serve_field_app(request: Request):
    """Serve the Truck Server mobile web interface."""
    return templates.TemplateResponse(request, "field_app.html", {
        "request": request,
        "field_token": get_settings().field_internal_token
    })

@app.get("/office/login", tags=["frontend"])
async def serve_office_login(request: Request):
    """Serve the office login page."""
    return templates.TemplateResponse(request, "login.html", {"request": request})

@app.post("/office/login", tags=["frontend"])
async def process_office_login(request: Request, access_code: str = Form(...)):
    """Process office login."""
    settings = get_settings()
    if access_code == settings.office_internal_token:
        response = RedirectResponse(url="/office", status_code=303)
        response.set_cookie(
            key="office_auth",
            value=access_code,
            httponly=True,
            secure=(settings.app_env == "production"),
            samesite="lax"
        )
        return response
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": "Invalid Access Code"})

def _fetch_active_jobs_sync():
    conn = get_connection()
    try:
        cursor = conn.execute('''
            SELECT id, homeowner_name, address_line1, city, state, status, created_at
            FROM jobs
            WHERE status != 'CLOSED'
            ORDER BY created_at DESC
        ''')
        return [dict(r) for r in cursor]
    finally:
        conn.close()

@app.get("/office", tags=["frontend"])
async def serve_office_dashboard(request: Request):
    """Serve the Office Control Center desktop dashboard."""
    jobs = await asyncio.to_thread(_fetch_active_jobs_sync)
    active_jobs = len(jobs)
    ready_to_invoice = sum(1 for j in jobs if j["status"] in ("INSPECTION_COMPLETED", "FINAL_INSPECTION"))
    recent_leads = sum(1 for j in jobs if j["status"] == "LEAD_CAPTURED")
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request, 
        "jobs": jobs,
        "active_jobs": active_jobs,
        "recent_leads": recent_leads,
        "ready_to_invoice": ready_to_invoice,
        "office_token": get_settings().office_internal_token
    })

@app.get("/office/jobs/{job_id}", tags=["frontend"])
async def serve_job_detail(request: Request, job_id: str):
    """Serve the unified Job Overview dashboard."""
    from fastapi import HTTPException
    job = await asyncio.to_thread(_fetch_job_sync, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return templates.TemplateResponse(request, "job_detail.html", {
        "request": request, 
        "job": job,
        "office_token": get_settings().office_internal_token
    })
