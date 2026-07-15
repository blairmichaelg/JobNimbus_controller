"""
ARQ Worker task for processing supplement events.

This coordinates the entire Zero-Cost InsurTech Supplement pipeline:
1. Extract deterministic EV data via pdfplumber.
2. Extract multimodal SoL data via Gemini File API.
3. Reconcile both using the pure Python math engine.
4. Generate the narrative using Gemini.
5. Render the final PDF via ReportLab.
"""

import asyncio
from typing import Optional
import structlog

from app.services.pdf_extractor import extract_eagleview_data
from app.services.ai_service import AIService
from app.core.reconciliation import reconcile
from app.core.code_router import parse_code_files, get_relevant_codes
from app.services.pdf_generator import PDFGenerator
from app.core.database import get_connection, insert_job_document, update_job_status, JobStatus
from app.services.supplement_engine import SupplementEngine
from app.core.supplement_models import EagleViewData

logger = structlog.get_logger("app.workers.supplement_processor")


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


def generate_and_gate_flags(job_id: str, ice_barrier_required: bool, ev_data: EagleViewData) -> bool:
    """
    Evaluates DB rules and persists them to supplement_flags if the climate gate permits it.
    Also calculates dynamic quantities for specific rules (e.g. IWS rolls).
    Returns True if any flag requires manual review due to bad input data.
    """
    conn = get_connection()
    import uuid
    manual_review_required = False
    try:
        # Fetch all seeded rules
        cursor = conn.execute("SELECT * FROM supplement_rules")
        rules = cursor.fetchall()
        flags_to_insert = []
        for rule in rules:
            # CLIMATE GATE: If rule is climate dependent but job doesn't require it, SKIP.
            if bool(rule["climate_dependent"]) and not ice_barrier_required:
                continue
            
            quantity_delta = 1.0  # Default to 1 for most triggered rules
            notes = "Triggered via deterministic pipeline"
            
            # Use deterministic math engine if applicable
            if rule["required_child_code"] == "RFG IWS":
                try:
                    pitch = float(ev_data.predominant_pitch.split('/')[0])
                except (ValueError, AttributeError):
                    pitch = 0.0
                
                
                # IWS roll calculation requires pitch, eave LF, and valley LF
                try:
                    quantity_delta = SupplementEngine.calculate_ice_and_water_rolls(
                        pitch=pitch,
                        eave_length_ft=ev_data.eaves_lf,
                        valley_length_ft=ev_data.valley_lf
                    )
                except ValueError as e:
                    quantity_delta = 0.0
                    notes = f"MANUAL REVIEW REQUIRED: {e}"
                    manual_review_required = True

            flags_to_insert.append((
                str(uuid.uuid4()),
                job_id,
                rule["id"],
                1,
                float(quantity_delta),
                notes
            ))
        
        if flags_to_insert:
            conn.executemany('''
                INSERT INTO supplement_flags (id, job_id, rule_id, triggered, quantity_delta, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', flags_to_insert)
            conn.commit()
            
        return manual_review_required
    finally:
        conn.close()

import json as _json

def _fetch_latest_report_sync(job_id: str) -> dict | None:
    """
    Fetches the most recently committed reconciliation snapshot
    for a job. Returns None if no snapshot exists yet.
    """
    conn = get_connection()
    try:
        cursor = conn.execute(
            """SELECT report_json FROM supplement_reports
               WHERE job_id = ? ORDER BY created_at DESC LIMIT 1""",
            (job_id,)
        )
        row = cursor.fetchone()
        return _json.loads(row["report_json"]) if row else None
    finally:
        conn.close()

async def process_supplement_event(
    ctx: dict, job_id: str, 
    ev_pdf_path: Optional[str] = None, sol_pdf_path: Optional[str] = None, 
    resume: bool = False,
    ev_sha256: Optional[str] = None, ev_doc_id: Optional[str] = None,
    sol_sha256: Optional[str] = None, sol_doc_id: Optional[str] = None
) -> dict:
    """
    ARQ Task to handle the complete supplement request flow.
    If resume=True, it skips parsing and gating, validates flags are resolved,
    and proceeds directly to narrative/PDF generation.
    """
    log = logger.bind(job_id=job_id)
    log.info("supplement_processing_started", ev_pdf=ev_pdf_path, sol_pdf=sol_pdf_path, resume=resume)

    # 0. Fetch Job Context (Threaded)
    job_dict = await asyncio.to_thread(_fetch_job_context_sync, job_id)

    from pathlib import Path
    SUPPLEMENT_VAULT = Path("data/field_docs")
    vault_dir = SUPPLEMENT_VAULT / job_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    permanent_pdf_path = vault_dir / "Supplement_Request.pdf"

    temp_pdf_path = None
    try:
        if resume:
            # Verify no flags are pending manual review
            conn = get_connection()
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM supplement_flags WHERE job_id = ? AND notes LIKE 'MANUAL REVIEW REQUIRED%'", (job_id,))
                if cursor.fetchone()[0] > 0:
                    log.warning("resume_rejected_unresolved_flags")
                    return {"status": "rejected", "reason": "unresolved_manual_flags"}
                
                from app.core.supplement_models import DiscrepancyReport
                report_dict = await asyncio.to_thread(_fetch_latest_report_sync, job_id)
                if not report_dict:
                    log.error("resume_rejected_no_report", job_id=job_id)
                    await asyncio.to_thread(
                        update_job_status, job_id, JobStatus.PIPELINE_FAILED,
                        "Resume attempted but no saved report found. Re-run from scratch."
                    )
                    return {"status": "failed", "reason": "no_saved_report"}

                report = DiscrepancyReport.model_validate(report_dict)
            finally:
                conn.close()
            
            code_index = await asyncio.to_thread(parse_code_files)
            codes = "" # No codes needed if resuming or fetch from DB if needed
        else:
            if ev_pdf_path is None or sol_pdf_path is None:
                raise ValueError("PDF paths must be provided when not resuming")
            
            # 1. Extract EV Data
            ev_data, ev_hash = await extract_eagleview_data(str(ev_pdf_path))

            # 2. Extract SoL Data
            from app.services.document_parser import parse_statement_of_loss
            from pathlib import Path
            try:
                sol_data = await parse_statement_of_loss(
                    Path(sol_pdf_path), 
                    source_doc_sha256=sol_sha256 or "unknown", 
                    source_doc_id=sol_doc_id or "unknown"
                )
            except ValueError as e:
                await asyncio.to_thread(update_job_status, job_id, JobStatus.PENDING_MANUAL_REVIEW, f"SoL Parse failed: {str(e)}")
                return {"status": "halted_for_review"}

            unverified_items = [li for li in sol_data.line_items if not li.verified]
            if unverified_items:
                conn = get_connection()
                try:
                    import uuid
                    flags_to_insert = []
                    for item in unverified_items:
                        flag_note = (
                            f"Carrier math mismatch on line item: {item.activity_code} "
                            f"'{item.description}'. "
                            f"Expected: (qty={item.quantity.value} × "
                            f"rate={item.unit_price.value}) + tax={item.tax.value} "
                            f"= {item.claimed_rcv.value}. "
                            f"Source page: {item.quantity.evidence[0].page if item.quantity.evidence else 'unknown'}. "
                            f"MANUAL VERIFICATION REQUIRED before supplement generation."
                        )
                        log.warning("sol_math_mismatch_flagged", code=item.activity_code)
                        flags_to_insert.append((
                            str(uuid.uuid4()), job_id, "synthetic_math_rule", 1, 0.0, flag_note
                        ))
                    
                    if flags_to_insert:
                        conn.executemany('''
                            INSERT INTO supplement_flags (id, job_id, rule_id, triggered, quantity_delta, notes)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', flags_to_insert)
                        conn.commit()
                finally:
                    conn.close()

                await asyncio.to_thread(
                    update_job_status,
                    job_id,
                    JobStatus.PENDING_MANUAL_REVIEW,
                    f"{len(unverified_items)} carrier line items failed math verification."
                )
                return {"status": "halted_for_review"}


            # 3. Reconcile
            report = await asyncio.to_thread(reconcile, ev_data, sol_data, job_id=job_id)
            
            # Persist report snapshot for potential resume
            def _save_report_sync():
                _conn = get_connection()
                try:
                    import uuid as _uuid
                    _conn.execute(
                        """INSERT INTO supplement_reports
                           (id, job_id, report_json, created_at)
                           VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                        (str(_uuid.uuid4()), job_id, report.model_dump_json())
                    )
                    _conn.commit()
                finally:
                    _conn.close()
            await asyncio.to_thread(_save_report_sync)

            # 4. Load Target Building Codes (Zero-Cost RAG)
            code_index = await asyncio.to_thread(parse_code_files)
            codes = await asyncio.to_thread(get_relevant_codes, report, code_index)

            # 4.5. Generate and Gate Supplement Flags
            ice_barrier_required = bool(job_dict.get("ice_barrier_required")) if job_dict.get("ice_barrier_required") is not None else False
            manual_review_required = await asyncio.to_thread(generate_and_gate_flags, job_id, ice_barrier_required, ev_data)
            
            if manual_review_required:
                await asyncio.to_thread(update_job_status, job_id, JobStatus.PENDING_MANUAL_REVIEW, note="Manual flag entry required due to malformed extraction.")
                log.info("pipeline_halted_for_review")
                return {"status": "halted_for_review"}

        # 5. Generate Narrative
        ai_service = AIService()
        narrative = await ai_service.generate_supplement_narrative(report, codes)

        # 6. Generate PDF
        pdf_gen = PDFGenerator()
        temp_pdf_path = await pdf_gen.generate_supplement_pdf(report, narrative, job=job_dict)
        
        import shutil
        shutil.move(temp_pdf_path, permanent_pdf_path)
        temp_pdf_path = None  # Nullify so finally block skips deletion

        # 7. Vault Document & Update State (Threaded)
        if not ctx.get("is_test"):
            await asyncio.to_thread(insert_job_document, job_id, "Supplement_Request.pdf", "application/pdf", str(permanent_pdf_path))
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
        if temp_pdf_path:
            from pathlib import Path
            Path(temp_pdf_path).unlink(missing_ok=True)
