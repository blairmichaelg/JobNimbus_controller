"""
ARQ Worker: Supplement Pipeline orchestrator.
"""

import structlog
from app.core.pipeline import run_supplement_pipeline

logger = structlog.get_logger("app.workers.supplement_processor")

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
) -> dict:
    return await run_supplement_pipeline(
        job_id, ev_pdf_path, sol_pdf_path, ev_sha256, ev_doc_id, sol_sha256, sol_doc_id, resume
    )
