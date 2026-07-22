"""
ARQ Worker: Supplement Pipeline orchestrator.
"""

import structlog
from app.core.pipeline import run_supplement_pipeline

logger = structlog.get_logger("app.workers.supplement_processor")

VALID_WORKER_ROLES = {"admin", "field", "office"}

async def process_supplement_event(
    ctx: dict,
    job_id: str,
    ev_pdf_path: str = "",
    sol_pdf_path: str = "",
    ev_sha256: str = "",
    ev_doc_id: str = "",
    sol_sha256: str = "",
    sol_doc_id: str = "",
    resume: bool = False,
    role: str | None = None,
) -> dict:
    # Sanitize role — never trust caller-supplied role blindly
    if role not in VALID_WORKER_ROLES:
        logger.warning("invalid_role_in_payload", job_id=job_id, role=role)
        role = "field"  # safe default — least privilege

    ctx["role"] = role
    ALLOWED_SUPPLEMENT_ROLES = {"admin", "operations"}
    if ctx.get("role") not in ALLOWED_SUPPLEMENT_ROLES:
        logger.warning("role_not_allowed_for_supplement", role=role)
        return {"status": "forbidden", "reason": "role_not_allowed_for_supplement"}

    return await run_supplement_pipeline(
        job_id, ev_pdf_path, sol_pdf_path, ev_sha256, ev_doc_id, sol_sha256, sol_doc_id, resume
    )
