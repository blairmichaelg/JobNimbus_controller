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
from pydantic import BaseModel

from app.core.database import get_connection, update_job_status
from app.services.pdf_extractor import extract_eagleview_data
from app.core.reconciliation import reconcile
from app.core.supplement_models import StatementOfLoss
from app.services.qbo_export import generate_qbo_invoice
from app.services.pdf_generator import PDFGenerator
from app.api.field_routes import get_inspection_summary, SIGNED_AGREEMENTS_DIR
from app.core.job_costing import compute_job_profitability
from app.core.database import insert_material_order, JobStatus

logger = structlog.get_logger("app.api.office_routes")

router = APIRouter(prefix="/api/office", tags=["office_ux"])

FIELD_DOCS_DIR = Path("field_docs")
EXPORT_DIR = Path("generated_exports")

class FinancialsPayload(BaseModel):
    revenue: float
    materials: float
    labor: float
    overhead_pct: float = 0.25
    commission_pct: float = 0.10

class MaterialOrderPayload(BaseModel):
    supplier_name: str
    delivery_date: str

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

@router.post("/jobs/{job_id}/financials")
async def update_job_financials(job_id: str, payload: FinancialsPayload):
    """
    Process pre-build job costing parameters from the Office Dashboard.
    Calculates exact margin profiles and logs alerts if profitability is too low.
    """
    try:
        # Calculate precise financials
        results = compute_job_profitability(
            revenue=payload.revenue,
            materials=payload.materials,
            labor=payload.labor,
            overhead_pct=payload.overhead_pct,
            commission_pct=payload.commission_pct
        )
        
        # Directive 4: Low Margin Alert
        if results["gross_margin"] < 0.35:
            logger.warning(
                "low_margin_alert", 
                job_id=job_id, 
                gross_margin=results["gross_margin"],
                revenue=payload.revenue,
                direct_costs=results["direct_costs"]
            )
            
        # Store raw parameters in DB
        upsert_financials(
            job_id=job_id,
            carrier_rcv=payload.revenue,
            material_cost=payload.materials,
            labor_cost=payload.labor,
            overhead_pct=payload.overhead_pct,
            canvasser_commission_pct=payload.commission_pct
        )
        
        return {"status": "success", "financials": results}
    except Exception as e:
        logger.error("job_costing_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to calculate and save financials.")

@router.post("/jobs/{job_id}/material_order")
async def generate_material_order(job_id: str, payload: MaterialOrderPayload):
    """
    Triggers the generation of the supplier PO and updates job status to MATERIAL_ORDERED.
    """
    job_dir = FIELD_DOCS_DIR / job_id
    pdf_path = job_dir / "eagleview.pdf"
    
    if not pdf_path.exists():
        raise HTTPException(status_code=400, detail="EagleView PDF not found. Cannot generate PO.")
        
    try:
        # Rebuild BOM
        ev_data = await extract_eagleview_data(pdf_path)
        empty_sol = StatementOfLoss(line_items=[], overhead_and_profit_included=True)
        report = reconcile(ev_data, empty_sol, job_id, waste_factor=0.15)
        bom = report.material_bom
        
        # Fetch Homeowner Info
        conn = get_connection()
        try:
            cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            job_row = cursor.fetchone()
            if not job_row:
                raise HTTPException(status_code=404, detail="Job not found in database.")
            job_dict = dict(job_row)
        finally:
            conn.close()
            
        # Generate PO PDF
        pdf_gen = PDFGenerator()
        await pdf_gen.generate_material_po(job_dict, bom, payload.supplier_name, payload.delivery_date)
        
        # Insert Record & Update State
        insert_material_order(job_id, payload.supplier_name, payload.delivery_date, bom.model_dump_json())
        update_job_status(job_id, JobStatus.MATERIAL_ORDERED)
        
        return {"status": "success"}
    except Exception as e:
        logger.error("material_order_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to process material order")

@router.get("/jobs/{job_id}/docs/po")
async def download_po(job_id: str, supplier_name: str):
    """Returns the generated Material Purchase Order PDF."""
    safe_name = supplier_name.replace(' ', '_')
    po_path = FIELD_DOCS_DIR / job_id / f"PO_{safe_name}.pdf"
    
    if not po_path.exists():
        raise HTTPException(status_code=404, detail="Purchase Order not found.")
        
    return FileResponse(path=po_path, filename=f"PO_{safe_name}.pdf", media_type="application/pdf")

@router.get("/jobs/{job_id}/docs/cancellation")
async def download_cancellation(job_id: str):
    """Dynamically generates and returns the Georgia Notice of Cancellation."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found.")
        job_dict = dict(row)
    finally:
        conn.close()
        
    pdf_gen = PDFGenerator()
    pdf_path = await pdf_gen.generate_notice_of_cancellation(job_dict)
    
    return FileResponse(path=pdf_path, filename=f"Notice_of_Cancellation_{job_id[:8]}.pdf", media_type="application/pdf")

@router.get("/jobs/{job_id}/docs/completion")
async def download_completion(job_id: str, completion_date: str):
    """Dynamically generates and returns the Certificate of Completion."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found.")
        job_dict = dict(row)
    finally:
        conn.close()
        
    pdf_gen = PDFGenerator()
    pdf_path = await pdf_gen.generate_certificate_of_completion(job_dict, completion_date)
    
    return FileResponse(path=pdf_path, filename=f"Certificate_of_Completion_{job_id[:8]}.pdf", media_type="application/pdf")
