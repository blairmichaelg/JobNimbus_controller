"""
FastAPI HTTP surface for the Office Control Center Dashboard (V4 Strike 3).
Handles job retrieval, EagleView uploads, and generated artifact downloads.
"""

import json
from pathlib import Path
import structlog
from typing import List, Dict, Any

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse

from app.core.database import get_connection, update_job_status
from app.services.pdf_extractor import extract_eagleview_data
from app.core.reconciliation import reconcile
from app.core.supplement_models import StatementOfLoss
from app.services.qbo_export import generate_qbo_invoice
from app.services.pdf_generator import PDFGenerator
from app.api.field_routes import get_inspection_summary, SIGNED_AGREEMENTS_DIR

logger = structlog.get_logger("app.api.office_routes")

router = APIRouter(prefix="/api/office", tags=["office_ux"])

FIELD_DOCS_DIR = Path("field_docs")
EXPORT_DIR = Path("generated_exports")


@router.get("/jobs")
async def get_all_jobs() -> List[Dict[str, Any]]:
    """Retrieve all jobs from the local CRM ordered by creation date."""
    conn = get_connection()
    try:
        cursor = conn.execute('''
            SELECT id, homeowner_name, address_line1, city, state, postal_code, 
                   phone, email, claim_number, insurer_name, status, status_history, created_at
            FROM jobs
            ORDER BY created_at DESC
        ''')
        rows = cursor.fetchall()
        
        jobs = []
        for r in rows:
            job_dict = dict(r)
            job_dict["status_history"] = json.loads(job_dict["status_history"]) if job_dict["status_history"] else []
            jobs.append(job_dict)
            
        return jobs
    except Exception as e:
        logger.error("failed_to_fetch_jobs", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch jobs")
    finally:
        conn.close()


@router.post("/jobs/{job_id}/eagleview")
async def upload_eagleview(job_id: str, file: UploadFile = File(...)):
    """
    Trigger the V4 Automath pipeline.
    Saves PDF, extracts metrics, calculates BOM, generates QBO CSV, and updates status.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Must upload a PDF file.")

    job_dir = FIELD_DOCS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_dir / "eagleview.pdf"

    # 1. Save File
    try:
        content = await file.read()
        pdf_path.write_bytes(content)
        logger.info("eagleview_pdf_uploaded", job_id=job_id, bytes=len(content))
    except Exception as e:
        logger.error("eagleview_upload_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save EagleView PDF")

    # 2. Extract Data
    try:
        ev_data = await extract_eagleview_data(pdf_path)
    except Exception as e:
        logger.error("eagleview_extraction_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    # 3. Calculate Math
    # We use an empty SoL because we bypass Carrier Reconciliation for this V4 flow
    empty_sol = StatementOfLoss(line_items=[], overhead_and_profit_included=True)
    
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT homeowner_name FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        homeowner_name = row["homeowner_name"] if row else "Unknown Customer"
    finally:
        conn.close()

    try:
        report = reconcile(ev_data, empty_sol, job_id, waste_factor=0.15)
        bom = report.material_bom
    except Exception as e:
        logger.error("automath_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to calculate Material BOM")

    # 4. Export QBO CSV & Update Status
    try:
        csv_path = generate_qbo_invoice(job_id, bom, customer_name=homeowner_name)
        logger.info("qbo_invoice_generated", job_id=job_id, path=csv_path)
    except Exception as e:
        logger.error("qbo_export_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate QuickBooks CSV")

    return {"status": "success", "message": "EagleView processed, Math Engine complete, QBO CSV generated."}


@router.get("/jobs/{job_id}/evidence_grid")
async def download_evidence_grid(job_id: str):
    """
    Builds the InspectionJob from the local filesystem and cache,
    generates the ReportLab PDF Evidence Grid, and returns the file download.
    """
    try:
        # Construct the InspectionJob using the field_routes helper
        job = await get_inspection_summary(job_id)
        
        if not job.photos:
            raise HTTPException(status_code=404, detail="No photos found for this job.")

        # Look for signature
        sig_path = SIGNED_AGREEMENTS_DIR / f"{job_id}_signature.png"
        signature_to_pass = str(sig_path) if sig_path.exists() else None

        # Generate PDF
        pdf_gen = PDFGenerator()
        pdf_path = await pdf_gen.generate_evidence_grid(job, signature_to_pass)
        
        return FileResponse(
            path=pdf_path,
            filename=f"Evidence_Grid_{job_id[:8]}.pdf",
            media_type="application/pdf"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("evidence_grid_download_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate Evidence Grid PDF")


@router.get("/jobs/{job_id}/qbo_export")
async def download_qbo_export(job_id: str):
    """Returns the generated QBO CSV for the given job."""
    csv_path = EXPORT_DIR / f"INV-{job_id[:8].upper()}_QBO.csv"
    
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="QBO Export not found for this job.")
        
    return FileResponse(
        path=csv_path,
        filename=f"INV-{job_id[:8].upper()}_QBO.csv",
        media_type="text/csv"
    )
