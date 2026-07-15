"""
ARQ Worker: Retail Quote Generator

For RETAIL job_type jobs only. Completely bypasses Gemini
and the supplement engine.

Pipeline:
1. Fetch EagleView total_squares from jobs table.
2. Apply 3-tier pricing from pricing table.
3. Generate Retail_Quote.pdf showing all three options.
4. Transition job to RETAIL_QUOTE_GENERATED.
"""

import asyncio
import structlog
from app.core.database import (
    get_connection, update_job_status,
    insert_job_document, get_pricing_ledger, JobStatus
)
from app.services.pdf_generator import PDFGenerator

logger = structlog.get_logger(
    "app.workers.retail_quote_processor"
)


async def process_retail_quote(
    ctx: dict,
    job_id: str
) -> dict:
    log = logger.bind(job_id=job_id)
    log.info("retail_quote_started")

    # 1. Fetch job and EagleView geometry
    def _fetch_job():
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Job {job_id} not found.")
            return dict(row)
        finally:
            conn.close()

    job = await asyncio.to_thread(_fetch_job)

    total_area_sf = job.get("ev_total_area_sf")
    if not total_area_sf or total_area_sf <= 0:
        update_job_status(
            job_id,
            JobStatus.PENDING_OPERATOR_REVIEW,
            "Retail quote blocked: ev_total_area_sf is missing. "
            "Enter geometry in Triage and re-queue."
        )
        return {"status": "pending_review",
                "reason": "missing_ev_data"}

    # 2. Convert SF to squares (1 square = 100 SF)
    # Apply 10% waste factor standard in the industry
    raw_squares = total_area_sf / 100.0
    billable_squares = round(raw_squares * 1.10, 2)

    # 3. Fetch tier pricing
    pricing = await asyncio.to_thread(get_pricing_ledger)
    tiers = [
        {
            "name":        "Standard (3-Tab)",
            "description": "Certainteed XT25 or equivalent. "
                           "25-year limited warranty.",
            "price_per_sq": pricing.get(
                "retail_standard_per_sq", 350.0
            ),
        },
        {
            "name":        "Architectural (Dimensional)",
            "description": "Owens Corning Duration or equivalent. "
                           "Lifetime limited warranty.",
            "price_per_sq": pricing.get(
                "retail_arch_per_sq", 420.0
            ),
        },
        {
            "name":        "Premium / Metal Shingle",
            "description": "Metal shingle system. "
                           "50-year structural warranty.",
            "price_per_sq": pricing.get(
                "retail_premium_per_sq", 580.0
            ),
        },
    ]
    for tier in tiers:
        tier["total_price"] = round(
            tier["price_per_sq"] * billable_squares, 2
        )

    # 4. Generate PDF
    pdf_gen = PDFGenerator()
    quote_pdf_path = await pdf_gen.generate_retail_quote(
        job=job,
        billable_squares=billable_squares,
        tiers=tiers
    )

    # 5. Register in document vault
    import hashlib
    from pathlib import Path
    pdf_hash = hashlib.sha256(
        Path(quote_pdf_path).read_bytes()
    ).hexdigest()
    insert_job_document(
        job_id=job_id,
        filename="Retail_Quote.pdf",
        file_type="RETAIL_QUOTE_PDF",
        storage_path=quote_pdf_path,
        sha256_hash=pdf_hash
    )

    # 6. Transition job
    update_job_status(
        job_id,
        JobStatus.RETAIL_QUOTE_GENERATED,
        f"Retail quote generated: {billable_squares} sq, "
        f"3 tiers."
    )

    log.info("retail_quote_complete",
             squares=billable_squares)
    return {"status": "complete",
            "squares": billable_squares,
            "quote_pdf": quote_pdf_path}
