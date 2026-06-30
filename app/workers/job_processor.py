"""
Job processing worker — the core async pipeline.

This worker is the heart of the middleware. It picks up enqueued jobs
from the ARQ Redis queue and executes the full pipeline:

1. Hydration: GET the canonical job/contact record from JobNimbus
2. Translation: Map obfuscated cf_* fields to human-readable keys
3. Quarantine Revalidation: Confirm status == QUARANTINE_STATUS (authoritative check)
4. Cognitive Processing: Send translated data to Gemini AI
5. Document Generation: Render PDFs if applicable
6. Egress/Execution: Push results back to JobNimbus (or mock in DRY_RUN mode)
"""

from pathlib import Path
import structlog

from app.config import get_settings
from app.core.field_mapper import FieldMapper
from app.services.ai_service import AIService
from legacy_jobnimbus.jobnimbus_client import JobNimbusClient
from app.services.pdf_generator import PDFGenerator

logger = structlog.get_logger("app.workers.job_processor")


async def process_jobnimbus_event(ctx: dict, jnid: str, payload: dict) -> None:
    """
    Process a single JobNimbus webhook event.

    Args:
        ctx: ARQ worker context (contains Redis connection, jn_client).
        jnid: The JobNimbus entity ID extracted from the webhook.
        payload: The original webhook payload containing the event data.
    """
    jn_client = ctx.get("jn_client")
    if not jn_client:
        logger.error("job_processor_missing_client")
        raise RuntimeError("JobNimbusClient not found in worker context.")

    settings = get_settings()
    log = logger.bind(jnid=jnid)
    log.info("job_processing_started", event_type=payload.get("event_type"))

    # --- 1. Hydration ---
    record_type = payload.get("record_type_name", "").lower()
    try:
        if record_type == "contact":
            canonical_data = await jn_client.get_contact(jnid)
        else:
            # Default to get_job if record_type is missing or 'job'
            canonical_data = await jn_client.get_job(jnid)
    except Exception as exc:
        log.error("job_hydration_failed", error=str(exc))
        raise

    log.info("job_hydrated", record_type=record_type)

    # --- 2. Authoritative Quarantine Check ---
    canonical_status = canonical_data.get("status_name")
    if canonical_status != settings.quarantine_status:
        log.warning(
            "job_dropped_quarantine_failed",
            canonical_status=canonical_status,
            required_status=settings.quarantine_status,
        )
        return  # Drop the task early

    # --- 3. Translation ---
    mapper = FieldMapper()
    translated_data = mapper.to_human(canonical_data)
    log.info("job_translated")

    # --- 4. Cognitive Processing ---
    ai_service = AIService()
    decision = await ai_service.analyze_job_data(translated_data)

    action = decision.get("action")
    if action == "error":
        log.error("job_pipeline_ai_error", reasoning=decision.get("reasoning"))
        return
    elif action == "ignore":
        log.info("job_pipeline_ai_ignored", reasoning=decision.get("reasoning"))
        return
    elif action == "update_status":
        log.info("job_pipeline_ai_update_status", reasoning=decision.get("reasoning"))
        # Phase 5 scope primarily focuses on generate_document, but we can do a simple update if needed
        return

    # --- 5. Document Generation & Egress ---
    if action == "generate_document":
        doc_data = decision.get("document_data", {})
        pdf_gen = PDFGenerator()
        pdf_path = await pdf_gen.generate_estimate_pdf(doc_data, jnid)

        try:
            # Egress: Upload the generated PDF to JobNimbus
            await jn_client.upload_document(
                jnid=jnid,
                filepath=pdf_path,
                description="AI Generated Estimate",
            )

            # Egress: Update the CRM status
            await jn_client.update_job(jnid, {"status_name": "Estimate Uploaded"})

            log.info("job_pipeline_egress_complete", pdf_path=pdf_path)

        finally:
            # Clean up the temporary PDF file to avoid disk space leaks
            path_obj = Path(pdf_path)
            if path_obj.exists():
                path_obj.unlink()
                log.debug("job_pipeline_cleaned_temp_file", filepath=pdf_path)
