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
from fastapi import FastAPI, Request, Response, Form, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.webhooks import router as webhook_router
from app.api.field_routes import router as field_router
from app.api.office_routes import router as office_router
from app.api.operations_routes import router as operations_router
from app.api.auth_routes import router as auth_router
from app.api.admin_reps_routes import router as admin_reps_router
from app.api.admin_jobs_routes import router as admin_jobs_router
from app.api.auth import verify_admin, verify_accounting, verify_field, verify_office_role, get_current_role
from app.config import get_settings
from app.core.notifications import notifier
from app.core.cache import init_db as init_cache_db
from app.core.database import run_migrations as init_crm_db, get_connection, list_field_reps, _fetch_job_sync, get_job_documents
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
        quarantine_status=settings.quarantine_status,
    )
    
    # Stark visibility for Dev/Prod split
    if settings.app_env.lower() == "prod":
        logger.info("[PROD MODE] Using data/wickham.db on port 8000")
    else:
        logger.info("[DEV MODE] Using data/wickham_dev.db on port 8001")

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


    # Close the ARQ Redis pool (Phase 3)
    if hasattr(app.state, "redis_pool"):
        await app.state.redis_pool.close()

    logger.info("application_stopped")


app = FastAPI(
    title="Wickham Roofing AI Orchestrator",
    description="Standalone CRM orchestrator and Google Gemini AI middleware.",
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

def days_since(date_str: str) -> int:
    if not date_str:
        return 0
    from datetime import datetime
    try:
        # Expected format: 2026-07-15 14:00:00 (SQLite CURRENT_TIMESTAMP)
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return (datetime.utcnow() - dt).days
    except Exception:
        return 0

templates.env.filters["days_since"] = days_since

# --- Mount Routers ---
app.include_router(webhook_router)
app.include_router(field_router)
app.include_router(office_router)
app.include_router(operations_router)
app.include_router(auth_router)
app.include_router(admin_reps_router)
app.include_router(admin_jobs_router)

@app.middleware("http")
async def auth_redirect_middleware(request: Request, call_next):
    """Redirect unauthenticated browser requests to /login.
    API routes (/api/*) always return JSON 401 — no redirect.
    """
    response = await call_next(request)
    if (
        response.status_code == 401
        and not request.url.path.startswith("/api/")
        and not request.url.path.startswith("/auth/")
        and not request.url.path.startswith("/login")
        and not request.url.path.startswith("/health")
        and not request.url.path.startswith("/static/")
        and "text/html" in request.headers.get("accept", "")
    ):
        return RedirectResponse(
            url=f"/login?redirect_url={request.url.path}",
            status_code=303,
        )
    return response



@app.websocket("/ws/office")
async def office_ws(websocket: WebSocket):
    # Token validation before handshake accept
    from app.api.auth import decode_token
    token = websocket.query_params.get("token") or websocket.cookies.get("auth_token")
    if not token:
        await websocket.close(code=1008, reason="Unauthorized: Missing authentication token")
        return
    try:
        payload = decode_token(token)
        if payload.get("role") not in ["admin", "operations", "accounting"]:
            await websocket.close(code=1008, reason="Forbidden: Unauthorized role for office feed")
            return
    except Exception:
        await websocket.close(code=1008, reason="Unauthorized: Invalid token")
        return

    await notifier.connect(websocket, client_id="office_client", role=payload.get("role", "office"))
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
    }


# --- Frontend ---
@app.get("/field", tags=["frontend"])
async def serve_field_app(request: Request, role: str = Depends(verify_field)):
    """Serve the Truck Server mobile web interface."""
    return templates.TemplateResponse(request, "field_app.html", {
        "request": request,
        "field_token": request.cookies.get("auth_token", "")
    })

@app.get("/login", tags=["frontend"])
async def serve_login(request: Request, redirect_url: str = "/"):
    """Serve the universal login page with optional post-auth redirect target."""
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "redirect_url": redirect_url},
    )

@app.post("/login", tags=["frontend"])
async def process_login(request: Request, access_code: str = Form(...)):
    """Process login and route to persona dashboard based on PIN."""
    settings = get_settings()
    
    role = None
    redirect_url = "/"
    rep_name: str | None = None
    rep_id: str | None = None
    
    if access_code == settings.admin_pin:
        role = "admin"
        redirect_url = "/admin"
    elif access_code == settings.accounting_pin:
        role = "accounting"
        redirect_url = "/accounting"
    elif access_code == settings.operations_pin:
        role = "operations"
        redirect_url = "/api/operations/board"
    else:
        # Dynamic field rep lookup (Phase 9)
        from app.core.database import get_field_rep_by_pin
        rep = get_field_rep_by_pin(access_code)
        if rep:
            role = "field"
            rep_name = rep["name"]
            rep_id = rep["id"]
            redirect_url = "/field"
        

        
    if role:
        from app.api.auth import create_access_token
        token = create_access_token(
            role,
            rep_name=rep_name if role == "field" else None,
            rep_id=rep_id if role == "field" else None,
        )
        
        response = RedirectResponse(url=redirect_url, status_code=303)
        response.set_cookie(
            key="auth_token",
            value=token,
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


@app.get("/admin", tags=["frontend"])
async def serve_admin_dashboard(request: Request, role: str = Depends(verify_admin)):
    """Serve the Admin Kanban Board."""
    jobs = await asyncio.to_thread(_fetch_active_jobs_sync)
    return templates.TemplateResponse(request, "admin_dashboard.html", {
        "request": request, 
        "jobs": jobs,
        "auth_token": request.cookies.get("auth_token", "")
    })

@app.get("/admin/reps", tags=["frontend"])
async def admin_reps_page(request: Request, role: str = Depends(get_current_role)):
    """Serve the Field Rep Management page (admin only)."""
    from fastapi import HTTPException
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admins only.")
    reps = await asyncio.to_thread(list_field_reps, True)
    return templates.TemplateResponse(
        request,
        "admin_reps.html",
        {
            "reps": reps,
            "role": role,
        },
    )

@app.get("/accounting", tags=["frontend"])
async def serve_accounting_dashboard(request: Request, role: str = Depends(verify_accounting)):
    """Serve the Accounting Ledger."""
    return templates.TemplateResponse(request, "accounting_dashboard.html", {
        "request": request, 
        "auth_token": request.cookies.get("auth_token", "")
    })


@app.get("/office/canvassing", tags=["frontend"])
async def serve_canvassing(request: Request, role: str = Depends(verify_office_role)):
    """Serve the Canvassing Targets dashboard."""
    conn = get_connection()
    try:
        cursor = conn.execute('''
            SELECT 
                s.zipcode,
                COUNT(s.id) as event_count,
                MAX(s.event_date) as last_event_date,
                MAX(s.hail_size_inches) as max_hail,
                COUNT(DISTINCT j.id) as total_leads,
                SUM(CASE WHEN j.status = 'LEAD_CAPTURED' THEN 1 ELSE 0 END) as active_leads
            FROM storm_events s
            LEFT JOIN jobs j ON j.postal_code = s.zipcode
            GROUP BY s.zipcode
            ORDER BY last_event_date DESC
            LIMIT 50
        ''')
        targets = [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

    return templates.TemplateResponse(request, "admin_canvassing.html", {
        "request": request,
        "role": role,
        "targets": targets,
        "auth_token": request.cookies.get("auth_token", "")
    })

@app.get("/office/jobs/{job_id}", tags=["frontend"])
async def serve_job_detail(request: Request, job_id: str, role: str = Depends(verify_office_role)):
    """Serve the unified Job Overview dashboard (for Admin, Operations, Accounting)."""
    from fastapi import HTTPException
    job = await asyncio.to_thread(_fetch_job_sync, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    documents = await asyncio.to_thread(get_job_documents, job_id)
    job["documents"] = documents

    if job.get("damage_signals"):
        import json
        try:
            job["damage_signals"] = json.loads(job["damage_signals"])
        except Exception:
            job["damage_signals"] = []
    else:
        job["damage_signals"] = []

    # Calculate Condition Index
    from app.api.field_routes import get_inspection_summary
    try:
        inspection_job = await get_inspection_summary(job_id, claims={"rep_name": "System", "role": "admin"})
    except Exception:
        # Fallback to empty inspection job if not available
        from app.core.inspection_models import InspectionJob
        import datetime
        inspection_job = InspectionJob(job_id=job_id, property_address="", inspection_date=datetime.datetime.now())
        
    from app.core.inspection_models import calculate_condition_index
    condition_index = calculate_condition_index(inspection_job, job["damage_signals"])

    # Fetch Suggested Dates of Loss
    storm_events = []
    if job.get("postal_code"):
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM storm_events WHERE zipcode = ? ORDER BY event_date DESC LIMIT 5",
                (job["postal_code"],)
            )
            storm_events = [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    return templates.TemplateResponse(request, "job_detail.html", {
        "request": request, 
        "job": job,
        "condition_index": condition_index,
        "storm_events": storm_events,
        "role": role,
        "auth_token": request.cookies.get("auth_token", "")
    })
