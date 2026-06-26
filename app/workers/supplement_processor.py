"""
ARQ Worker task for processing supplement events.

This coordinates the entire Zero-Cost InsurTech Supplement pipeline:
1. Extract deterministic EV data via pdfplumber.
2. Extract multimodal SoL data via Gemini File API.
3. Reconcile both using the pure Python math engine.
4. Generate the narrative using Gemini.
5. Render the final PDF via ReportLab.
"""

import os
from pathlib import Path
import structlog

from app.services.pdf_extractor import extract_eagleview_data
from app.services.ai_service import AIService
from app.core.reconciliation import reconcile
from app.services.pdf_generator import PDFGenerator

logger = structlog.get_logger("app.workers.supplement_processor")


def _load_building_codes() -> str:
    """Read building code texts from the building_codes directory."""
    codes_dir = Path("building_codes")
    codes_text = ""
    if codes_dir.exists():
        for txt_file in codes_dir.glob("*.txt"):
            try:
                codes_text += txt_file.read_text(encoding="utf-8") + "\n\n"
            except Exception as e:
                logger.warning("building_code_read_failed", file=txt_file.name, error=str(e))
    return codes_text


async def process_supplement_event(ctx: dict, jnid: str, ev_pdf_path: str, sol_pdf_path: str) -> dict:
    """
    ARQ Task to handle the complete supplement request flow.
    """
    log = logger.bind(jnid=jnid)
    log.info("supplement_processing_started", ev_pdf=ev_pdf_path, sol_pdf=sol_pdf_path)

    temp_pdf_path = None
    try:
        # 1. Extract EV Data
        ev_data = await extract_eagleview_data(ev_pdf_path)

        # 2. Extract SoL Data
        ai_service = AIService()
        sol_data = await ai_service.extract_sol_from_pdf(sol_pdf_path)

        # 3. Reconcile
        report = reconcile(ev_data, sol_data, job_id=jnid)

        # 4. Load Building Codes
        codes = _load_building_codes()

        # 5. Generate Narrative
        narrative = await ai_service.generate_supplement_narrative(report, codes)

        # 6. Generate PDF
        pdf_gen = PDFGenerator()
        temp_pdf_path = await pdf_gen.generate_supplement_pdf(report, narrative, jnid=jnid)

        # 7. Upload to CRM (mocked in tests, real in production if jn_client exists in ctx)
        if "jn_client" in ctx:
            jn_client = ctx["jn_client"]
            await jn_client.upload_document(
                jnid=jnid,
                filepath=temp_pdf_path,
                description="Wickham Roofing Supplement Request",
                file_type=1,
            )
            
            # Optional: Update status
            await jn_client.update_job(jnid, {"status_name": "Supplement Filed"})
            
        log.info("supplement_processing_complete")
        return {"status": "success", "pdf_path": temp_pdf_path}

    except Exception as exc:
        log.error("supplement_processing_failed", error=str(exc))
        raise
    finally:
        # Cleanup temporary PDF
        if temp_pdf_path and Path(temp_pdf_path).exists():
            try:
                # If we're not running in a standalone test where we want to keep the file, delete it.
                # Since we want to return it for the test script to see, we won't delete it here 
                # unless explicitly in a worker cleanup context. But standard behavior is to delete.
                # We'll leave it up to the caller to clean up in the test script, 
                # but in production, we should unlink it after upload.
                if "jn_client" in ctx:
                    Path(temp_pdf_path).unlink()
            except Exception as e:
                log.warning("temp_pdf_cleanup_failed", filepath=temp_pdf_path, error=str(e))
