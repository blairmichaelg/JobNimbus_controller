from __future__ import annotations

import structlog
from pathlib import Path
from typing import Any

from app.services.pdf_extractor import extract_eagleview_data
from app.core.reconciliation import reconcile
from app.core.supplement_models import StatementOfLoss
from app.services.qbo_export import generate_qbo_invoice
from app.core.database import update_job_status, JobStatus

logger = structlog.get_logger("app.core.pipeline")

async def run_full_office_pipeline(job_id: str, ev_pdf_path: Path, customer_name: str = "Unknown Customer") -> dict[str, Any]:
    """The Master Orchestrator for the V4 Pipeline.
    
    Strictly executes the chain: Parse EV PDF -> Calculate BOM -> Generate QBO CSV -> Transition Status.
    
    Args:
        job_id (str): The unique identifier for the job.
        ev_pdf_path (Path): Path to the uploaded EagleView PDF.
        customer_name (str, optional): The name of the homeowner/customer. Defaults to "Unknown Customer".
        
    Returns:
        dict[str, Any]: A dictionary containing the status, parsed EV data, BOM, and QBO CSV path.
        
    Raises:
        Exception: If any step in the orchestration pipeline fails.
    """
    log = logger.bind(job_id=job_id)
    log.info("master_pipeline_started", ev_pdf_path=str(ev_pdf_path))
    
    try:
        # 1. Parse EV PDF
        ev_data, ev_hash = await extract_eagleview_data(ev_pdf_path)
        log.info("pipeline_ev_parsed", sq=ev_data.total_area_sf / 100.0)

        import asyncio
        from app.core.database import _fetch_job_sync
        job_dict = await asyncio.to_thread(_fetch_job_sync, job_id)
        if job_dict and job_dict.get("flashing_lf") is not None and job_dict.get("step_flashing_lf") is not None:
            ev_data.flashing_lf = job_dict["flashing_lf"]
            ev_data.step_flashing_lf = job_dict["step_flashing_lf"]

        if ev_data.flashing_lf is None or ev_data.step_flashing_lf is None:
            await asyncio.to_thread(update_job_status, job_id, JobStatus.PENDING_OPERATOR_REVIEW, "Flashing/step-flashing measurements missing. Operator must enter manually before supplement can generate.")
            return {"status": "halted_for_review", "reason": "missing_flashing_data"}

        
        # 2. Calculate BOM
        from app.core.complexity import compute_complexity_score, calculate_dynamic_waste
        score = compute_complexity_score(ev_data)
        waste = calculate_dynamic_waste(score)
        empty_sol = StatementOfLoss(line_items=[], overhead_and_profit_included=True)
        report = reconcile(ev_data, empty_sol, job_id, waste_factor=waste)
        bom = report.material_bom
        log.info("pipeline_bom_calculated", field_bundles=bom.field_shingle_bundles)
        
        import asyncio
        # 3. Generate QBO CSV as a reference export (does NOT auto-invoice)
        csv_path = await asyncio.to_thread(generate_qbo_invoice, job_id, bom, customer_name)
        log.info("pipeline_qbo_generated", csv_path=csv_path)
        
        # 4. Transition Status to PENDING_OPERATOR_REVIEW
        await asyncio.to_thread(update_job_status, job_id, JobStatus.PENDING_OPERATOR_REVIEW, "EagleView parsed. BOM calculated. Awaiting operator review.")
        log.info("master_pipeline_completed")
        
        return {
            "status": "success",
            "ev_data": ev_data.model_dump(),
            "bom": bom.model_dump(),
            "qbo_csv_path": csv_path
        }
        
    except Exception as e:
        log.error("master_pipeline_failed", error=str(e))
        import asyncio
        await asyncio.to_thread(update_job_status, job_id, JobStatus.PIPELINE_FAILED, f"Pipeline crashed: {str(e)}")
        raise

async def generate_material_order_pipeline(job_id: str, supplier_name: str, delivery_date: str) -> dict[str, Any]:
    from app.services.ai_service import AIService
    from app.services.pdf_generator import PDFGenerator
    from app.core.database import _fetch_job_sync, insert_material_order
    from app.config import FIELD_DOCS_DIR
    import asyncio
    
    job_dir = FIELD_DOCS_DIR / job_id
    pdf_path = job_dir / "eagleview.pdf"
    if not pdf_path.exists():
        raise ValueError("EagleView PDF not found. Cannot generate PO.")
        
    ev_data, _ = await extract_eagleview_data(pdf_path)
    sol_pdf_path = job_dir / "statement_of_loss.pdf"
    if sol_pdf_path.exists():
        ai_svc = AIService()
        sol = await ai_svc.extract_sol_from_pdf(str(sol_pdf_path), job_id=job_id)
    else:
        sol = StatementOfLoss(line_items=[], overhead_and_profit_included=True)
        
    from app.core.complexity import compute_complexity_score, calculate_dynamic_waste
    score = compute_complexity_score(ev_data)
    dynamic_waste = calculate_dynamic_waste(score)
    report = await asyncio.to_thread(reconcile, ev_data, sol, job_id, dynamic_waste)
    bom = report.material_bom
    
    job_dict = await asyncio.to_thread(_fetch_job_sync, job_id)
    if not job_dict:
        raise ValueError("Job not found in database.")
        
    pdf_gen = PDFGenerator()
    await pdf_gen.generate_material_po(job_dict, bom, supplier_name, delivery_date)
    
    await asyncio.to_thread(insert_material_order, job_id, supplier_name, delivery_date, bom.model_dump_json())
    await asyncio.to_thread(update_job_status, job_id, JobStatus.MATERIAL_ORDERED)
    
    return {"status": "success"}

from app.core.database import get_connection, insert_job_document, get_pricing_ledger
"""
Retail Quote Generator Pipeline

For RETAIL job_type jobs only. Completely bypasses Gemini
and the supplement engine.

Pipeline:
1. Fetch EagleView total_squares from jobs table.
2. Apply 3-tier pricing from pricing table.
3. Generate Retail_Quote.pdf showing all three options.
4. Transition job to RETAIL_QUOTE_GENERATED.
"""



logger = structlog.get_logger("app.core.pipeline")


async def run_retail_quote_pipeline(job_id: str) -> dict:
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

from app.services.ai_service import AIService
"""
Rebuttal Letter Generator Pipeline

When a carrier denies or low-balls a supplement, this worker:
1. Fetches the original DiscrepancyReport from supplement_reports.
2. Fetches all triggered supplement_flags + IRC/MFG citations.
3. Feeds the denial text + forensic data into Gemini 2.5 Pro.
4. Generates a Rebuttal_Letter.pdf via PDFGenerator.
5. Registers it in job_documents and transitions job to
   SUPPLEMENT_SUBMITTED (ready for operator review + send).
"""





REBUTTAL_SYSTEM_PROMPT = """
You are a licensed public adjuster and insurance claims expert
specializing in roofing supplement disputes. You write formal,
legally-cited rebuttal letters on behalf of the roofing contractor.

Your rebuttals must:
1. Address each denial argument directly with a factual counter.
2. Cite specific IRC code sections, manufacturer specs, or Xactimate
   line item documentation for EVERY counter-argument.
3. Maintain a professional, non-confrontational tone.
4. Be structured as a formal business letter with numbered points.
5. End with a clear demand for the specific dollar amount or
   line items being disputed.

Do NOT invent citations. Only use citations from the provided
forensic context. If a carrier argument has no code counter,
say so plainly and argue from industry standard practice instead.
"""


async def run_rebuttal_pipeline(
    job_id: str,
    denial_text: str | None = None,
    denial_pdf_doc_id: str | None = None
) -> dict:
    log = logger.bind(job_id=job_id)
    log.info("rebuttal_processing_started")

    # 1. Fetch job context
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

    # 2. Fetch the original DiscrepancyReport snapshot
    def _fetch_report():
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT report_json FROM supplement_reports
                   WHERE job_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (job_id,)
            ).fetchone()
            return row["report_json"] if row else None
        finally:
            conn.close()

    report_json = await asyncio.to_thread(_fetch_report)

    # 3. Fetch triggered IRC/MFG citations
    def _fetch_citations():
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT r.required_child_code, r.citation_text,
                          r.citation_type, f.quantity_delta, f.notes
                   FROM supplement_flags f
                   JOIN supplement_rules r ON f.rule_id = r.id
                   WHERE f.job_id = ? AND f.triggered = 1""",
                (job_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    citations = await asyncio.to_thread(_fetch_citations)

    # 4. Resolve denial text (from direct paste or PDF doc)
    if not denial_text and denial_pdf_doc_id:
        def _fetch_denial_pdf_path():
            conn = get_connection()
            try:
                row = conn.execute(
                    "SELECT storage_path FROM job_documents "
                    "WHERE id = ?",
                    (denial_pdf_doc_id,)
                ).fetchone()
                return row["storage_path"] if row else None
            finally:
                conn.close()

        pdf_path = await asyncio.to_thread(_fetch_denial_pdf_path)
        if pdf_path:
            # Use pdfplumber to extract denial text from PDF
            import pdfplumber
            def _extract_denial():
                with pdfplumber.open(pdf_path) as pdf:
                    return "\\n".join(
                        p.extract_text() or ""
                        for p in pdf.pages
                    )
            denial_text = await asyncio.to_thread(_extract_denial)

    if not denial_text:
        denial_text = "(No denial text provided — generate general rebuttal based on supplement discrepancies.)"

    # 5. Build Gemini prompt
    citations_block = "\\n".join(
        f"- [{c['citation_type']}] {c['required_child_code']}: "
        f"{c['citation_text']} (qty delta: {c['quantity_delta']})"
        for c in citations
    )
    report_summary = (
        report_json[:3000]
        if report_json else "(No report snapshot available)"
    )

    user_prompt = f"""
CARRIER DENIAL TEXT:
{denial_text}

ORIGINAL SUPPLEMENT DISCREPANCY REPORT (JSON excerpt):
{report_summary}

TRIGGERED CODE CITATIONS FOR THIS JOB:
{citations_block}

HOMEOWNER: {job.get('homeowner_name', 'N/A')}
ADDRESS: {job.get('address_line1', 'N/A')},
         {job.get('city', 'N/A')}, {job.get('state', 'N/A')}
CLAIM #: {job.get('claim_number', 'N/A')}
INSURER: {job.get('insurer_name', 'N/A')}

Write a complete, professional rebuttal letter addressing the
carrier's denial. Use all relevant citations above. Structure
as a formal letter addressed to the carrier's claims department.
"""

    # 6. Call Gemini
    ai = AIService()
    try:
        rebuttal_narrative = await ai.generate_text(
            system_prompt=REBUTTAL_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            job_id=job_id,
            operation_type="rebuttal_generation"
        )
    except Exception as e:
        log.error("rebuttal_ai_failed", error=str(e))
        update_job_status(
            job_id, JobStatus.PIPELINE_FAILED,
            f"Rebuttal AI failed: {e}"
        )
        return {"status": "failed", "reason": str(e)}

    # 7. Generate Rebuttal PDF
    pdf_gen = PDFGenerator()
    rebuttal_pdf_path = await pdf_gen.generate_rebuttal_letter(
        job=job,
        denial_text=denial_text,
        rebuttal_narrative=rebuttal_narrative
    )

    # 8. Register in document vault
    import hashlib
    from pathlib import Path
    pdf_hash = hashlib.sha256(
        Path(rebuttal_pdf_path).read_bytes()
    ).hexdigest()
    insert_job_document(
        job_id=job_id,
        filename="Rebuttal_Letter.pdf",
        file_type="REBUTTAL_PDF",
        storage_path=rebuttal_pdf_path,
        sha256_hash=pdf_hash
    )

    # 9. Transition to SUPPLEMENT_SUBMITTED
    # (operator reviews and sends from their email client)
    update_job_status(
        job_id,
        JobStatus.SUPPLEMENT_SUBMITTED,
        "AI Rebuttal Letter generated. Ready for operator review."
    )

    log.info("rebuttal_processing_complete",
             pdf_path=rebuttal_pdf_path)
    return {"status": "complete",
            "rebuttal_pdf_path": rebuttal_pdf_path}

from pydantic import ValidationError

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
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM supplement_flags WHERE job_id = ?", (job_id,))
        
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
        conn.execute("COMMIT")
            
        return manual_review_required
    except Exception:
        conn.execute("ROLLBACK")
        raise
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

async def run_supplement_pipeline(job_id: str, ev_pdf_path: str, sol_pdf_path: str, ev_sha256: str, ev_doc_id: str, sol_sha256: str, sol_doc_id: str, resume: bool = False, ctx: dict = {}) -> dict:
    """
    ARQ Task to handle the complete supplement request flow.
    If resume=True, it skips parsing and gating, validates flags are resolved,
    and proceeds directly to narrative/PDF generation.
    """
    log = logger.bind(job_id=job_id)
    log.info("supplement_processing_started", ev_pdf=ev_pdf_path, sol_pdf=sol_pdf_path, resume=resume)

    # 0. Fetch Job Context (Threaded)
    job_dict = await asyncio.to_thread(_fetch_job_context_sync, job_id)
    
    job_type = job_dict.get("job_type", "INSURANCE")
    if job_type == "RETAIL":
        logger.warning("supplement_skipped_retail_job",
                       job_id=job_id)
        return {"status": "skipped", "reason": "retail_job"}

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

            from app.core.database import _fetch_job_sync
            job_dict = await asyncio.to_thread(_fetch_job_sync, job_id)
            if job_dict and job_dict.get("flashing_lf") is not None and job_dict.get("step_flashing_lf") is not None:
                ev_data.flashing_lf = job_dict["flashing_lf"]
                ev_data.step_flashing_lf = job_dict["step_flashing_lf"]

            if ev_data.flashing_lf is None or ev_data.step_flashing_lf is None:
                await asyncio.to_thread(update_job_status, job_id, JobStatus.PENDING_OPERATOR_REVIEW, "Flashing/step-flashing measurements missing. Operator must enter manually before supplement can generate.")
                return {"status": "halted_for_review", "reason": "missing_flashing_data"}


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
                await asyncio.to_thread(update_job_status, job_id, JobStatus.PENDING_OPERATOR_REVIEW, f"SoL Parse failed: {str(e)}")
                return {"status": "halted_for_review"}

            unverified_items = [li for li in sol_data.line_items if not li.verified]
            gross_rcv_unverified = not sol_data.financials.gross_rcv.verified if sol_data.financials else False
            
            if unverified_items or gross_rcv_unverified:
                conn = get_connection()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("DELETE FROM supplement_flags WHERE job_id = ? AND rule_id = 'synthetic_math_rule'", (job_id,))
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
                        
                    if gross_rcv_unverified:
                        flag_note = (
                            f"Carrier Gross RCV ({sol_data.financials.gross_rcv.value}) does not tie out "
                            f"to sum of line items. Estimate mathematical foundation is unverified."
                        )
                        log.warning("gross_rcv_mismatch_flagged")
                        flags_to_insert.append((
                            str(uuid.uuid4()), job_id, "synthetic_math_rule", 1, 0.0, flag_note
                        ))
                    
                    if flags_to_insert:
                        conn.executemany('''
                            INSERT INTO supplement_flags (id, job_id, rule_id, triggered, quantity_delta, notes)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', flags_to_insert)
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                finally:
                    conn.close()

                error_msg = []
                if unverified_items:
                    error_msg.append(f"{len(unverified_items)} carrier line items failed math verification.")
                if gross_rcv_unverified:
                    error_msg.append("Carrier Gross RCV mismatch.")
                
                await asyncio.to_thread(
                    update_job_status,
                    job_id,
                    JobStatus.PENDING_OPERATOR_REVIEW,
                    " ".join(error_msg)
                )
                
                if gross_rcv_unverified:
                    return {"status": "halted_for_review", "reason": "gross_rcv_mismatch"}
                return {"status": "halted_for_review"}
            else:
                # If there are NO unverified items, we must STILL clear out old flags
                conn = get_connection()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("DELETE FROM supplement_flags WHERE job_id = ? AND rule_id = 'synthetic_math_rule'", (job_id,))
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                finally:
                    conn.close()


            # 3. Reconcile
            from app.core.complexity import compute_complexity_score, calculate_dynamic_waste
            score = compute_complexity_score(ev_data)
            dynamic_waste = calculate_dynamic_waste(score)
            report = await asyncio.to_thread(reconcile, ev_data, sol_data, job_id, dynamic_waste)  # type: ignore
            
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
                await asyncio.to_thread(update_job_status, job_id, JobStatus.PENDING_OPERATOR_REVIEW, note="Manual flag entry required due to malformed extraction.")
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
        return {"status": "success", "pdf_path": str(permanent_pdf_path)}

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
