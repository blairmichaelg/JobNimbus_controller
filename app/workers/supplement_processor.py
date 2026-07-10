"""
ARQ Worker task for processing supplement events.

This coordinates the entire Zero-Cost InsurTech Supplement pipeline:
1. Extract deterministic EV data via pdfplumber.
2. Extract multimodal SoL data via Gemini File API.
3. Reconcile both using the pure Python math engine.
4. Generate the narrative using Gemini.
5. Render the final PDF via ReportLab.
"""

import structlog

from app.services.pdf_extractor import extract_eagleview_data
from app.services.ai_service import AIService
from app.core.reconciliation import reconcile
from app.core.code_router import parse_code_files, get_relevant_codes
from app.services.pdf_generator import PDFGenerator
from app.core.database import get_connection, insert_job_document, update_job_status, JobStatus

logger = structlog.get_logger("app.workers.supplement_processor")


import asyncio

def _fetch_job_context_sync(job_id: str) -> dict:
    """Synchronously fetch the job context from SQLite."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Job {job_id} not found in database.")
        return dict(row)
    finally:
        conn.close()


def generate_and_gate_flags(job_id: str, ice_barrier_required: bool) -> None:
    """
    Evaluates DB rules and persists them to supplement_flags if the climate gate permits it.
    """
    conn = get_connection()
    import uuid
    try:
        # Fetch all seeded rules
        cursor = conn.execute("SELECT * FROM supplement_rules")
        rules = cursor.fetchall()
        flags_to_insert = []
        for rule in rules:
            # CLIMATE GATE: If rule is climate dependent but job doesn't require it, SKIP.
            if bool(rule["climate_dependent"]) and not ice_barrier_required:
                continue
            
            # For demonstration, we simply insert a flag for all valid rules
            # In a real app, you'd execute rule["trigger_logic_name"] against the `report` or `ev_data`
            flags_to_insert.append((
                str(uuid.uuid4()),
                job_id,
                rule["id"],
                1,
                0.0,
                "Triggered via deterministic pipeline"
            ))
        
        if flags_to_insert:
            conn.executemany('''
                INSERT INTO supplement_flags (id, job_id, rule_id, triggered, quantity_delta, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', flags_to_insert)
            conn.commit()
    finally:
        conn.close()

async def process_supplement_event(ctx: dict, job_id: str, ev_pdf_path: str, sol_pdf_path: str) -> dict:
    """
    ARQ Task to handle the complete supplement request flow.
    """
    log = logger.bind(job_id=job_id)
    log.info("supplement_processing_started", ev_pdf=ev_pdf_path, sol_pdf=sol_pdf_path)

    # 0. Fetch Job Context (Threaded)
    job_dict = await asyncio.to_thread(_fetch_job_context_sync, job_id)

    temp_pdf_path = None
    try:
        # 1. Extract EV Data
        ev_data = await extract_eagleview_data(ev_pdf_path)

        # 2. Extract SoL Data
        ai_service = AIService()
        sol_data = await ai_service.extract_sol_from_pdf(sol_pdf_path, job_id=job_id)

        # 3. Reconcile
        report = await asyncio.to_thread(reconcile, ev_data, sol_data, job_id=job_id)

        # 4. Load Target Building Codes (Zero-Cost RAG)
        code_index = await asyncio.to_thread(parse_code_files)
        codes = await asyncio.to_thread(get_relevant_codes, report, code_index)

        # 4.5. Generate and Gate Supplement Flags
        ice_barrier_required = bool(job_dict.get("ice_barrier_required")) if job_dict.get("ice_barrier_required") is not None else False
        await asyncio.to_thread(generate_and_gate_flags, job_id, ice_barrier_required)

        # 5. Generate Narrative
        narrative = await ai_service.generate_supplement_narrative(report, codes)

        # 6. Generate PDF
        pdf_gen = PDFGenerator()
        temp_pdf_path = await pdf_gen.generate_supplement_pdf(report, narrative, job=job_dict)

        # 7. Vault Document & Update State (Threaded)
        if not ctx.get("is_test"):
            await asyncio.to_thread(insert_job_document, job_id, "Supplement_Request.pdf", "application/pdf", temp_pdf_path)
            await asyncio.to_thread(update_job_status, job_id, JobStatus.SUPPLEMENT_GENERATED)

        log.info("supplement_processing_complete")
        return {"status": "success", "pdf_path": temp_pdf_path}

    except Exception as exc:
        log.error("supplement_processing_failed", error=str(exc))
        if not ctx.get("is_test"):
            await asyncio.to_thread(update_job_status, job_id, JobStatus.PIPELINE_FAILED, note=str(exc))
        raise
    finally:
        # Cleanup temporary PDF
        pass
