"""
Resilient async HTTP client for the JobNimbus API.

Key design decisions:
- Uses httpx.AsyncClient for native async/await HTTP
- Automatic Bearer token injection via base headers
- Exponential backoff with jitter for 429 Too Many Requests
- Safe query parameter construction via httpx.QueryParams
  (avoids manual string concatenation & URL encoding bugs)
- DRY_RUN mode: mutation methods log payloads instead of firing
- All mutation URLs include ?skip=automation,notification&actor=... to
  prevent infinite webhook loops and ensure audit trail
"""

import asyncio
import math
import mimetypes
import random
from pathlib import Path
from typing import Any

import httpx
import structlog

from app.config import Settings, get_settings

logger = structlog.get_logger("app.services.jobnimbus_client")

# ---------------------------------------------------------------------------
# Retry / Backoff Constants
# ---------------------------------------------------------------------------
MAX_RETRIES = 5
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 60.0
JITTER_FACTOR = 0.5  # ±50% randomization on each delay


# ---------------------------------------------------------------------------
# Exponential Backoff Decorator
# ---------------------------------------------------------------------------
def retry_on_rate_limit(func):
    """
    Decorator: retry an async method on HTTP 429 with exponential backoff + jitter.

    Uses full-jitter strategy: delay = random(0, min(cap, base * 2^attempt))
    This spreads retries across time to avoid thundering herd on rate-limit reset.
    """

    async def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429:
                    # Non-rate-limit error — don't retry, propagate immediately
                    raise

                last_exception = exc

                # Calculate delay with full jitter
                exp_delay = BASE_DELAY_SECONDS * math.pow(2, attempt)
                capped_delay = min(exp_delay, MAX_DELAY_SECONDS)
                jittered_delay = capped_delay * (
                    1 + JITTER_FACTOR * (random.random() * 2 - 1)
                )
                jittered_delay = max(0.1, jittered_delay)  # Floor at 100ms

                # Check for Retry-After header (JN may provide this)
                retry_after = exc.response.headers.get("Retry-After")
                if retry_after:
                    try:
                        jittered_delay = max(jittered_delay, float(retry_after))
                    except ValueError:
                        pass

                logger.warning(
                    "rate_limited_retrying",
                    attempt=attempt + 1,
                    max_retries=MAX_RETRIES,
                    delay_seconds=round(jittered_delay, 2),
                    retry_after_header=retry_after,
                    url=str(exc.request.url),
                )
                await asyncio.sleep(jittered_delay)

        # All retries exhausted
        logger.error(
            "rate_limit_retries_exhausted",
            max_retries=MAX_RETRIES,
            url=str(last_exception.request.url) if last_exception else "unknown",
        )
        raise last_exception  # type: ignore[misc]

    return wrapper


def retry_on_transient_network_errors(func):
    """
    Decorator: retry an async method on httpx.RequestError (e.g. network glitches, DNS issues)
    with a small retry budget (max 2 retries, 0.5s base delay).
    """
    MAX_TRANSIENT_RETRIES = 3
    BASE_TRANSIENT_DELAY = 0.5

    async def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(MAX_TRANSIENT_RETRIES):
            try:
                return await func(*args, **kwargs)
            except httpx.RequestError as exc:
                last_exception = exc
                delay = BASE_TRANSIENT_DELAY * math.pow(2, attempt)
                logger.warning(
                    "transient_network_error_retrying",
                    attempt=attempt + 1,
                    max_retries=MAX_TRANSIENT_RETRIES,
                    delay_seconds=delay,
                    url=str(exc.request.url) if hasattr(exc, "request") else "unknown",
                    error=str(exc),
                )
                await asyncio.sleep(delay)

        # All retries exhausted
        logger.error(
            "transient_network_retries_exhausted",
            max_retries=MAX_TRANSIENT_RETRIES,
            url=str(last_exception.request.url) if hasattr(last_exception, "request") else "unknown",
        )
        raise last_exception  # type: ignore[misc]

    return wrapper


# ---------------------------------------------------------------------------
# JobNimbus API Client
# ---------------------------------------------------------------------------
class JobNimbusClient:
    """
    Async HTTP client for the JobNimbus CRM API.

    Usage:
        async with JobNimbusClient(settings) as client:
            job = await client.get_job("abc123")
            await client.update_job("abc123", {"status_name": "Approved"})
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = httpx.AsyncClient(
            base_url=self._settings.jobnimbus_base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {self._settings.jobnimbus_api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        self._dry_run = self._settings.dry_run
        self._actor_email = self._settings.jobnimbus_actor_email

        logger.info(
            "jobnimbus_client_initialized",
            base_url=self._settings.jobnimbus_base_url,
            actor=self._actor_email,
            dry_run=self._dry_run,
        )

    # --- Async Context Manager ---

    async def __aenter__(self) -> "JobNimbusClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        """Cleanly close the underlying httpx.AsyncClient."""
        await self._client.aclose()
        logger.info("jobnimbus_client_closed")

    # --- Query Parameter Builders ---

    def _read_params(self, **extra: Any) -> dict[str, str]:
        """
        Build query params for read-only (GET) requests.

        Actor is included so reads respect the actor's permissions/visibility.
        """
        params: dict[str, str] = {"actor": self._actor_email}
        params.update({k: str(v) for k, v in extra.items() if v is not None})
        return params

    def _mutation_params(self, **extra: Any) -> dict[str, str]:
        """
        Build query params for state-changing (PUT/POST) requests.

        CRITICAL: Always includes skip=automation,notification to prevent
        the infinite webhook loop described in spec constraint #3.
        """
        params: dict[str, str] = {
            "skip": "automation,notification",
            "actor": self._actor_email,
        }
        params.update({k: str(v) for k, v in extra.items() if v is not None})
        return params

    # --- Read Operations ---

    @retry_on_transient_network_errors
    @retry_on_rate_limit
    async def get_job(self, jnid: str) -> dict:
        """
        GET /jobs/{jnid} — Hydrate the full canonical job record.

        This is the authoritative data source. Webhook payloads are
        shallow/flat and must NOT be used for business logic.
        """
        logger.info("get_job_start", jnid=jnid)
        response = await self._client.get(
            f"/jobs/{jnid}",
            params=self._read_params(),
        )
        response.raise_for_status()
        data = response.json()
        logger.info("get_job_complete", jnid=jnid, status=response.status_code)
        return data

    @retry_on_transient_network_errors
    @retry_on_rate_limit
    async def get_contact(self, jnid: str) -> dict:
        """
        GET /contacts/{jnid} — Hydrate the full canonical contact record.
        """
        logger.info("get_contact_start", jnid=jnid)
        response = await self._client.get(
            f"/contacts/{jnid}",
            params=self._read_params(),
        )
        response.raise_for_status()
        data = response.json()
        logger.info("get_contact_complete", jnid=jnid, status=response.status_code)
        return data

    # --- Mutation Operations (DRY_RUN aware) ---

    @retry_on_rate_limit
    async def update_job(self, jnid: str, payload: dict) -> dict | None:
        """
        PUT /jobs/{jnid}?skip=automation,notification&actor=... — Update a job record.

        In DRY_RUN mode, logs the intended payload and returns None.
        """
        log = logger.bind(jnid=jnid, method="PUT", endpoint=f"/jobs/{jnid}")

        if self._dry_run:
            log.info("dry_run_update_job", payload=payload)
            return None

        log.info("update_job_start", payload=payload)
        response = await self._client.put(
            f"/jobs/{jnid}",
            params=self._mutation_params(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        log.info("update_job_complete", status=response.status_code)
        return data

    @retry_on_rate_limit
    async def create_task(self, payload: dict) -> dict | None:
        """
        POST /tasks?skip=automation,notification&actor=... — Create a CRM task.

        In DRY_RUN mode, logs the intended payload and returns None.
        """
        log = logger.bind(method="POST", endpoint="/tasks")

        if self._dry_run:
            log.info("dry_run_create_task", payload=payload)
            return None

        log.info("create_task_start", payload=payload)
        response = await self._client.post(
            "/tasks",
            params=self._mutation_params(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        log.info("create_task_complete", status=response.status_code)
        return data

    @retry_on_rate_limit
    async def upload_document(
        self,
        jnid: str,
        filepath: str | Path,
        description: str = "",
        file_type: int = 1,
    ) -> dict | None:
        """
        Upload a document (e.g., PDF) to a JobNimbus record via the 2-step
        presigned URL flow:

        Step 1: POST /files/v1/uploads/url
            - Sends file metadata + related entity ID
            - Returns a presigned S3 URL valid for 15 minutes

        Step 2: PUT <presigned_url>
            - Uploads the binary file data directly to S3

        Args:
            jnid: The JobNimbus entity ID to attach the file to.
            filepath: Local path to the file to upload.
            description: Optional file description.
            file_type: JN file type integer (1=Document, 2=Photo, 3=Email Attachment).

        In DRY_RUN mode, logs the intended upload and returns None.
        """
        filepath = Path(filepath)
        log = logger.bind(jnid=jnid, filepath=str(filepath), file_type=file_type)

        if not filepath.exists():
            log.error("upload_file_not_found")
            raise FileNotFoundError(f"Upload file not found: {filepath}")

        if self._dry_run:
            log.info(
                "dry_run_upload_document",
                file_size_bytes=filepath.stat().st_size,
                description=description,
            )
            return None

        # --- Step 1: Request presigned URL ---
        log.info("upload_step1_requesting_presigned_url")

        # Determine content type
        content_type = (
            mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"
        )

        step1_payload = {
            "related": [jnid],
            "type": file_type,
            "description": description or filepath.name,
            "contentType": content_type,
            "fileName": filepath.name,
        }

        response = await self._client.post(
            "/files/v1/uploads/url",
            params=self._mutation_params(),
            json=step1_payload,
        )
        response.raise_for_status()
        step1_data = response.json()

        presigned_url = step1_data.get("url")
        if not presigned_url:
            log.error("upload_step1_no_presigned_url", response_data=step1_data)
            raise ValueError("JobNimbus did not return a presigned upload URL")

        log.info(
            "upload_step1_complete", presigned_url_domain=presigned_url.split("/")[2]
        )

        # --- Step 2: PUT binary data to presigned URL ---
        log.info("upload_step2_uploading_binary")

        # Use a fresh httpx client for the S3 PUT (different auth, different base URL)
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as s3_client:
            file_data = await asyncio.to_thread(filepath.read_bytes)
            s3_response = await s3_client.put(
                presigned_url,
                content=file_data,
                headers={"Content-Type": content_type},
            )
            s3_response.raise_for_status()

        log.info(
            "upload_step2_complete",
            status=s3_response.status_code,
            file_size_bytes=len(file_data),
        )

        return step1_data
