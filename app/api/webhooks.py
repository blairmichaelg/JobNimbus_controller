"""
Webhook ingestion endpoint for JobNimbus.

Receives POST requests from JobNimbus webhooks, validates the
shared API key via constant-time comparison, applies the quarantine
filter (fast-reject for non-test jobs), and enqueues valid events
into the ARQ Redis queue for async processing.

Security:
- Custom x-api-key header validation (JN does NOT sign webhooks with HMAC)
- Constant-time comparison via secrets.compare_digest to prevent timing attacks

Quarantine Filter (dual-check pattern):
- Fast-reject here based on the shallow payload's status_name (best-effort)
- Authoritative re-verification happens post-hydration in the worker (Phase 4)
"""

import secrets

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings

logger = structlog.get_logger("app.api.webhooks")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Pydantic Model — Incoming Webhook Payload
# ---------------------------------------------------------------------------
class WebhookPayload(BaseModel):
    """
    Represents the flat JSON payload from a JobNimbus webhook.

    JobNimbus payloads are shallow and unpredictable — the set of fields
    varies by record type and event. We extract the fields we need and
    allow everything else to pass through via extra='allow'.

    Note: JobNimbus may use either 'jnid' or 'id' as the entity identifier.
    We accept both and normalize to 'jnid'.
    """

    model_config = ConfigDict(extra="allow")

    jnid: str | None = Field(
        default=None, description="JobNimbus entity ID (primary key)"
    )
    id: str | None = Field(default=None, description="Alternate entity ID field")
    record_type_name: str | None = Field(
        default=None, description="Entity type: 'contact', 'job', 'task', etc."
    )
    status_name: str | None = Field(
        default=None, description="Current workflow status of the entity"
    )
    event_type: str | None = Field(
        default=None, description="Event type: 'created', 'modified', 'deleted'"
    )

    @property
    def entity_id(self) -> str | None:
        """Normalize entity ID — prefer 'jnid', fall back to 'id'."""
        return self.jnid or self.id


# ---------------------------------------------------------------------------
# Security Dependency — x-api-key Validation
# ---------------------------------------------------------------------------
async def verify_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Validate the x-api-key header against the configured webhook secret.

    Uses secrets.compare_digest for constant-time comparison to prevent
    timing attacks. This is our only authentication layer since JobNimbus
    does NOT sign webhooks with HMAC.
    """
    if x_api_key is None:
        logger.warning("webhook_auth_missing_header")
        raise HTTPException(status_code=401, detail="Missing x-api-key header")

    if not secrets.compare_digest(x_api_key, settings.webhook_secret):
        logger.warning("webhook_auth_invalid_key")
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Webhook Route
# ---------------------------------------------------------------------------
@router.post("/jobnimbus", dependencies=[Depends(verify_api_key)])
async def receive_jobnimbus_webhook(
    payload: WebhookPayload,
    request: Request,
) -> dict:
    """
    Ingest a JobNimbus webhook event.

    Flow:
    1. Log the incoming webhook receipt
    2. Fast-reject if status_name != QUARANTINE_STATUS
    3. Enqueue the jnid + event to the ARQ Redis queue
    4. Return 200 OK immediately (ack before processing)
    """
    settings = get_settings()
    entity_id = payload.entity_id

    # --- Step 1: Log receipt ---
    logger.info(
        "webhook_received",
        jnid=entity_id,
        status_name=payload.status_name,
        record_type=payload.record_type_name,
        event_type=payload.event_type,
    )

    # --- Step 2: Quarantine Filter (fast-reject) ---
    # This is a best-effort check on the shallow payload.
    # The authoritative check happens post-hydration in the worker (Phase 4).
    if payload.status_name != settings.quarantine_status:
        logger.debug(
            "webhook_quarantine_rejected",
            jnid=entity_id,
            payload_status=payload.status_name,
            required_status=settings.quarantine_status,
        )
        return {"status": "ignored", "reason": "quarantine"}

    # --- Step 3: Validate we have an entity ID ---
    if not entity_id:
        logger.warning(
            "webhook_missing_entity_id",
            payload_keys=list(payload.model_dump().keys()),
        )
        return {"status": "ignored", "reason": "missing_entity_id"}

    # --- Step 4: Enqueue for async processing ---
    redis_pool = request.app.state.redis_pool

    try:
        await redis_pool.enqueue_job(
            "process_jobnimbus_event",
            jnid=entity_id,
            payload=payload.model_dump(),
        )
    except Exception as e:
        logger.error(
            "webhook_enqueue_failed",
            jnid=entity_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=503, detail="Service Unavailable - Queue full or offline"
        )

    logger.info(
        "webhook_enqueued",
        jnid=entity_id,
        event_type=payload.event_type,
    )

    return {"status": "queued", "jnid": entity_id}
