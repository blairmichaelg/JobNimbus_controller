"""
ARQ Worker: Rebuttal Letter Generator

When a carrier denies or low-balls a supplement, this worker:
1. Fetches the original DiscrepancyReport from supplement_reports.
2. Fetches all triggered supplement_flags + IRC/MFG citations.
3. Feeds the denial text + forensic data into Gemini 2.5 Pro.
4. Generates a Rebuttal_Letter.pdf via PDFGenerator.
5. Registers it in job_documents and transitions job to
   SUPPLEMENT_SUBMITTED (ready for operator review + send).
"""

import asyncio
import structlog
from app.core.database import (
    get_connection, update_job_status, insert_job_document,
    JobStatus
)
from app.services.ai_service import AIService
from app.services.pdf_generator import PDFGenerator

logger = structlog.get_logger("app.workers.rebuttal_processor")

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


async def process_rebuttal(
    ctx: dict,
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
