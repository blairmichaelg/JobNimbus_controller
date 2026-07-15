"""
ARQ Worker: Escalation Demand Letter Generator

Triggers manually when an operator hits the SLA exceed threshold.
Uses Gemini to generate a formal legal demand letter citing
delay and requesting immediate action.
"""

import asyncio, hashlib
import structlog
from pathlib import Path
from app.core.database import (
    get_connection, insert_job_document
)
from app.services.pdf_generator import PDFGenerator
import google.generativeai as genai
from app.config import get_settings

logger = structlog.get_logger("app.workers.escalation_processor")

async def process_escalation(ctx: dict, job_id: str) -> dict:
    log = logger.bind(job_id=job_id)
    log.info("escalation_processing_started")

    def _fetch():
        conn = get_connection()
        try:
            return dict(conn.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,)
            ).fetchone())
        finally:
            conn.close()

    job = await asyncio.to_thread(_fetch)
    
    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    prompt = f"""
    You are an assertive legal assistant for Wickham Roofing.
    Generate the body of a formal demand letter to an insurance carrier.
    
    Context:
    Homeowner: {job.get('homeowner_name', 'N/A')}
    Claim Number: {job.get('claim_number', 'N/A')}
    Insurer: {job.get('insurer_name', 'N/A')}
    
    Instructions:
    Write a 3-paragraph letter stating that we submitted a supplement 
    and have not received a response beyond the acceptable timeline.
    Demand an immediate status update and approval.
    Be highly professional but firm.
    DO NOT include the date, signature block, or addresses (these will be added by the PDF generator).
    Only output the paragraphs of the letter.
    """
    
    def _call_gemini():
        response = model.generate_content(prompt)
        return response.text.strip()
        
    letter_body = await asyncio.to_thread(_call_gemini)
    
    pdf_gen = PDFGenerator()
    pdf_path = await pdf_gen.generate_escalation_letter(job, letter_body)
    
    pdf_hash = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    insert_job_document(
        job_id=job_id,
        filename="Escalation_Demand.pdf",
        file_type="ESCALATION_PDF",
        storage_path=pdf_path,
        sha256_hash=pdf_hash
    )
    
    def _mark():
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE jobs SET escalation_sent_at = CURRENT_TIMESTAMP WHERE id = ?",
                (job_id,)
            )
            conn.commit()
        finally:
            conn.close()
            
    await asyncio.to_thread(_mark)
    
    log.info("escalation_processing_complete")
    return {"status": "complete", "pdf_path": pdf_path}
