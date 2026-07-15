"""
FastAPI HTTP surface for the Office Control Center Dashboard (V4 Strike 3).
Handles job retrieval, EagleView uploads, and generated artifact downloads.
"""

import json
import asyncio
from pathlib import Path
import structlog
from typing import List, Dict, Optional, Union, Any

from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Form, Request, BackgroundTasks, Body
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

templates = Jinja2Templates(directory="app/templates")

from app.core.database import get_connection, update_job_status
from app.services.pdf_extractor import extract_eagleview_data
from app.core.reconciliation import reconcile
from app.core.supplement_models import StatementOfLoss
from app.services.pdf_generator import PDFGenerator
from app.api.field_routes import get_inspection_summary, SIGNED_AGREEMENTS_DIR
from app.core.job_costing import compute_job_profitability
from app.core.database import insert_material_order, insert_schedule, JobStatus, backup_database, upsert_financials, insert_job_document, get_job_document_by_hash
from app.core.pipeline import run_full_office_pipeline
from app.api.auth import verify_admin
from app.core.upload_utils import stream_upload_safely

logger = structlog.get_logger("app.api.office_routes")

router = APIRouter(prefix="/api/office", tags=["office_ux"], dependencies=[Depends(verify_admin)])



FIELD_DOCS_DIR = Path("data/field_docs")
EXPORT_DIR = Path("generated_exports")

def _fetch_homeowner_name_sync(job_id: str) -> str:
    """
    Fetch the homeowner's name for a given job synchronously.

    Args:
        job_id (str): The unique identifier of the job.

    Returns:
        str: The homeowner's name or 'Unknown Customer' if not found.
    """
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT homeowner_name FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        return str(row["homeowner_name"]) if row else "Unknown Customer"
    finally:
        conn.close()

def _fetch_job_sync(job_id: str) -> Optional[Dict[str, Union[str, float, int, None]]]:
    """
    Fetch a complete job record synchronously.

    Args:
        job_id (str): The unique identifier of the job.

    Returns:
        Optional[Dict[str, Union[str, float, int, None]]]: A dictionary representing the job record, or None.
    """
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

class FinancialsPayload(BaseModel):
    revenue: float
    carrier_rcv: float
    materials: float
    labor: float
    deductible: float = 0.0
    acv_payment: float = 0.0
    recoverable_depreciation: float = 0.0
    overhead_pct: float = 0.25
    commission_pct: float = 0.10
    permits_fee: float = 0.0

class ProductionPayload(BaseModel):
    supplier_name: str
    delivery_date: str
    crew_name: str
    install_date: str

class MaterialOrderPayload(BaseModel):
    supplier_name: str
    delivery_date: str

@router.get("/jobs")
def get_all_jobs() -> List[Dict[str, Union[str, float, int, list, None]]]:
    """
    Retrieve all jobs from the local CRM ordered by creation date.
    
    Returns:
        List[Dict[str, Union[str, float, int, list, None]]]: A list of job records.
    """
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

@router.get("/jobs/{job_id}")
def get_job_details(job_id: str) -> Dict[str, Union[Dict[str, Union[str, float, int, list, None]], List[Dict[str, Union[str, float, int, None]]], None]]:
    """
    Retrieve unified job details across all production tables.
    
    Args:
        job_id (str): The unique identifier of the job.
        
    Returns:
        Dict[str, Union[Dict, List, None]]: Aggregated job data including financials, schedule, and docs.
    """
    conn = get_connection()
    try:
        # Get Job Metadata
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        job_row = cursor.fetchone()
        if not job_row:
            raise HTTPException(status_code=404, detail="Job not found.")
        job_dict = dict(job_row)
        job_dict["status_history"] = json.loads(job_dict["status_history"]) if job_dict["status_history"] else []
        
        # Get Financials
        cursor = conn.execute("SELECT * FROM financials WHERE job_id = ?", (job_id,))
        fin_row = cursor.fetchone()
        
        # Get Schedule
        cursor = conn.execute("SELECT * FROM schedule WHERE job_id = ?", (job_id,))
        sched_row = cursor.fetchone()
        
        # Get Material Order (Most recent)
        cursor = conn.execute("SELECT * FROM material_orders WHERE job_id = ? ORDER BY delivery_date DESC LIMIT 1", (job_id,))
        mat_row = cursor.fetchone()
        
        fin_dict = dict(fin_row) if fin_row else None
        if fin_dict:
            # Dynamically compute exact margins
            margins = compute_job_profitability(
                revenue=fin_dict["revenue"],
                materials=fin_dict["material_cost"],
                labor=fin_dict["labor_cost"],
                overhead_pct=fin_dict["overhead_pct"],
                commission_pct=fin_dict["canvasser_commission_pct"]
            )
            fin_dict["computed_margins"] = margins

        # Get Documents
        cursor = conn.execute("SELECT * FROM job_documents WHERE job_id = ? ORDER BY created_at DESC", (job_id,))
        doc_rows = cursor.fetchall()
        docs = [dict(r) for r in doc_rows]

        return {
            "job": job_dict,
            "financials": fin_dict,
            "schedule": dict(sched_row) if sched_row else None,
            "material_order": dict(mat_row) if mat_row else None,
            "documents": docs
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("failed_to_fetch_job_details", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch job details")
    finally:
        conn.close()


@router.post("/jobs/{job_id}/eagleview")
async def upload_eagleview(job_id: str, file: UploadFile = File(...)):
    """
    Trigger the V4 Automath pipeline.
    Saves PDF, extracts metrics, calculates BOM, generates QBO CSV, and updates status.
    """
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Must upload a PDF file.")

    job_dir = FIELD_DOCS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_dir / "eagleview.pdf"

    # 1. Save File & Get Hash
    try:
        file_hash = await stream_upload_safely(
            file, 
            pdf_path,
            max_bytes=25 * 1024 * 1024,
            allowed_magic_bytes=[b"%PDF-"]
        )
        logger.info("eagleview_pdf_uploaded", job_id=job_id, size=getattr(file, "size", 0), sha256=file_hash)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("eagleview_upload_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save EagleView PDF")


    # 2. Check for duplicate hash
    existing_doc = await asyncio.to_thread(get_job_document_by_hash, job_id, file_hash)
    if existing_doc:
        logger.warning("idempotent_upload_prevented", job_id=job_id, filename="eagleview.pdf", sha256=file_hash)
        pdf_path.unlink(missing_ok=True)
        return {"status": "success", "message": "Duplicate file detected. Skipped pipeline.", "pipeline_result": None}

    # 3. Get Homeowner Name for QBO
    try:
        homeowner_name = await asyncio.to_thread(_fetch_homeowner_name_sync, job_id)
    except Exception as e:
        logger.error("eagleview_homeowner_fetch_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch homeowner name")

    # 4. Trigger Master Orchestrator
    try:
        result = await run_full_office_pipeline(job_id, pdf_path, customer_name=homeowner_name)
        # Register document with hash
        await asyncio.to_thread(insert_job_document, job_id, "eagleview.pdf", "application/pdf", str(pdf_path), file_hash)
    except Exception as e:
        logger.error("master_pipeline_failed_route", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Pipeline Orchestration Failed: {str(e)}")

    return {"status": "success", "message": "Master Pipeline complete, QBO CSV generated.", "pipeline_result": result}


@router.post("/jobs/{job_id}/supplement_docs")
async def upload_supplement_docs(
    request: Request,
    job_id: str, 
    ev_file: UploadFile = File(...), 
    sol_file: UploadFile = File(...)
):
    """
    Upload both EagleView and Statement of Loss PDFs to trigger the Supplement pipeline.
    Injects the background task directly into the ARQ queue.
    """
    if ev_file.content_type != "application/pdf" or sol_file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Both files must be PDFs.")

    job_dir = FIELD_DOCS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    ev_path = job_dir / "eagleview.pdf"
    sol_path = job_dir / "statement_of_loss.pdf"

    try:
        ev_hash = await stream_upload_safely(ev_file, ev_path, max_bytes=25 * 1024 * 1024, allowed_magic_bytes=[b"%PDF-"])
        sol_hash = await stream_upload_safely(sol_file, sol_path, max_bytes=25 * 1024 * 1024, allowed_magic_bytes=[b"%PDF-"])
        
        logger.info("supplement_docs_uploaded", job_id=job_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("supplement_docs_upload_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save PDFs")


    # Deduplication check
    existing_ev = await asyncio.to_thread(get_job_document_by_hash, job_id, ev_hash)
    existing_sol = await asyncio.to_thread(get_job_document_by_hash, job_id, sol_hash)
    
    if existing_ev and existing_sol:
        logger.warning("idempotent_upload_prevented", job_id=job_id, sha256=ev_hash)
        ev_path.unlink(missing_ok=True)
        sol_path.unlink(missing_ok=True)
        return {"status": "success", "message": "Duplicate files detected. Skipped enqueue."}

    try:
        ev_sha256 = ev_hash   # Already computed by stream_upload_safely
        sol_sha256 = sol_hash # Already computed by stream_upload_safely
        
        # Insert them right away
        ev_doc_id = await asyncio.to_thread(
            insert_job_document, job_id, ev_path.name, "EAGLEVIEW_PDF", str(ev_path), ev_sha256
        )
        sol_doc_id = await asyncio.to_thread(
            insert_job_document, job_id, sol_path.name, "SOL_PDF", str(sol_path), sol_sha256
        )

        await request.app.state.redis_pool.enqueue_job(
            "process_supplement_event",
            job_id=job_id,
            ev_pdf_path=str(ev_path),
            sol_pdf_path=str(sol_path),
            ev_sha256=ev_sha256,
            ev_doc_id=ev_doc_id,
            sol_sha256=sol_sha256,
            sol_doc_id=sol_doc_id
        )
        
        logger.info("supplement_task_enqueued", job_id=job_id)
    except Exception as e:
        logger.error("supplement_enqueue_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to queue supplement task")

    return {"status": "success", "message": "Supplement generation enqueued."}


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
        raise HTTPException(status_code=500, detail="Failed to generate Evidence Grid.")


@router.get("/jobs/{job_id}/docs/download/{doc_id}")
def download_job_document(job_id: str, doc_id: str):
    """
    Download a file from the Universal Document Vault.
    """
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT storage_path, filename, file_type FROM job_documents WHERE id = ? AND job_id = ?", (doc_id, job_id))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document not found.")
        
        path = Path(row["storage_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="File is missing from disk.")
            
        return FileResponse(path, media_type=row["file_type"], filename=row["filename"])
    finally:
        conn.close()


@router.get("/download/{filename}")
def download_export(filename: str):
    """
    Download a generated CSV or PDF from the exports directory.
    """
    filename = Path(filename).name
    if not filename or filename.startswith('.'):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    file_path = EXPORT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
        
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )

@router.post("/jobs/{job_id}/docs/upload")
async def upload_job_document(job_id: str, file_type: str = Form(...), file: UploadFile = File(...)):
    """Upload a miscellaneous document to the universal vault."""
    valid_types = ["application/pdf", "image/jpeg", "image/png"]
    actual_type = file.content_type
    if actual_type not in valid_types:
        raise HTTPException(status_code=400, detail="Must upload a PDF, JPEG, or PNG.")

    job_dir = FIELD_DOCS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # Sanitize and assign a safe filename
    safe_name = Path(file.filename or "unknown").name
    pdf_path = job_dir / safe_name

    try:
        file_hash = await stream_upload_safely(
            file, 
            pdf_path,
            max_bytes=25 * 1024 * 1024,
            allowed_magic_bytes=[b"%PDF-", b"\xFF\xD8\xFF", b"\x89PNG\r\n\x1A\n"]
        )
        
        from app.core.database import get_job_document_by_hash
        existing_doc = await asyncio.to_thread(get_job_document_by_hash, job_id, file_hash)
        if existing_doc:
            logger.warning("idempotent_upload_prevented", job_id=job_id, filename=safe_name, sha256=file_hash)
            pdf_path.unlink(missing_ok=True)
            return {"status": "success", "filename": safe_name, "message": "Duplicate file detected."}
            
        try:
            await asyncio.to_thread(insert_job_document, job_id, safe_name, actual_type, str(pdf_path), file_hash)
        except Exception:
            pdf_path.unlink(missing_ok=True)
            raise
            
        logger.info("job_document_uploaded", job_id=job_id, filename=safe_name, size=getattr(file, "size", 0), sha256=file_hash)
        return {"status": "success", "filename": safe_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("job_document_upload_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save document")

@router.get("/jobs/{job_id}/docs/inspection_letter")
async def get_inspection_letter(job_id: str):
    job = await asyncio.to_thread(_fetch_job_sync, job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = FIELD_DOCS_DIR / job_id
    ev_pdf = job_dir / "eagleview.pdf"
    if not ev_pdf.exists():
        raise HTTPException(400, "EagleView not yet uploaded. Cannot generate letter.")
        
    ev_data_obj = await extract_eagleview_data(ev_pdf)
    ev_data = ev_data_obj.model_dump() if hasattr(ev_data_obj, 'model_dump') else dict(ev_data_obj)

    inspection_summary = {"damage_count": 0, "predominant_damage_type": "None", "severity": "Low"}
    if job.get("inspection_notes"):
        inspection_summary["severity"] = str(job["inspection_notes"])
    
    gen = PDFGenerator()
    try:
        pdf_path = await gen.generate_inspection_letter(job, ev_data, inspection_summary)
        return FileResponse(path=pdf_path, filename="Inspection_Letter.pdf", media_type="application/pdf")
    except Exception as e:
        logger.error("inspection_letter_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate Inspection Letter")

@router.get("/jobs/{job_id}/qbo_export")
def download_qbo_export(job_id: str):
    """Returns the generated QBO CSV for the given job."""
    csv_path = EXPORT_DIR / f"INV-{job_id[:8].upper()}_QBO.csv"
    
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="QBO Export not found for this job.")
        
    return FileResponse(
        path=csv_path,
        filename=f"INV-{job_id[:8].upper()}_QBO.csv",
        media_type="text/csv"
    )

def _sync_update_job_financials(job_id: str, payload: FinancialsPayload):
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
        revenue=payload.revenue,
        carrier_rcv=payload.carrier_rcv,
        material_cost=payload.materials,
        labor_cost=payload.labor,
        overhead_pct=payload.overhead_pct,
        canvasser_commission_pct=payload.commission_pct,
        permits_fee=payload.permits_fee
    )
    return results

@router.post("/jobs/{job_id}/financials")
async def update_job_financials(job_id: str, payload: FinancialsPayload, bg_tasks: BackgroundTasks):
    """
    Process pre-build job costing parameters from the Office Dashboard.
    Calculates exact margin profiles and logs alerts if profitability is too low.
    """
    try:
        results = await asyncio.to_thread(_sync_update_job_financials, job_id, payload)
        
        # Trigger Hot Backup
        bg_tasks.add_task(backup_database)
        
        return {"status": "success", "financials": results}
    except Exception as e:
        logger.error("job_costing_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to calculate and save financials.")


def _sync_update_job_production(job_id: str, payload: ProductionPayload):
    # Dummy BOM JSON for now, in a real scenario we'd pull the actual calculated BOM
    dummy_bom = json.dumps({"status": "scheduled_for_delivery"})
    
    insert_material_order(
        job_id=job_id,
        supplier_name=payload.supplier_name,
        delivery_date=payload.delivery_date,
        bom_json=dummy_bom
    )
    
    insert_schedule(
        job_id=job_id,
        crew_name=payload.crew_name,
        install_date=payload.install_date,
        delivery_date=payload.delivery_date,
        status="SCHEDULED"
    )
    
    update_job_status(job_id, JobStatus.INSTALL_SCHEDULED, f"Scheduled with {payload.crew_name} on {payload.install_date}")

@router.post("/jobs/{job_id}/production")
async def update_job_production(job_id: str, payload: ProductionPayload, bg_tasks: BackgroundTasks):
    """
    Unified route to set both material orders and installation schedule.
    Transitions job to INSTALL_SCHEDULED.
    """
    try:
        await asyncio.to_thread(_sync_update_job_production, job_id, payload)
        
        bg_tasks.add_task(backup_database)
        
        return {"status": "success", "message": "Production scheduled."}
    except Exception as e:
        logger.error("production_update_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to schedule production.")

@router.post("/jobs/{job_id}/material_order")
async def generate_material_order(job_id: str, payload: MaterialOrderPayload, bg_tasks: BackgroundTasks):
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
        sol_pdf_path = job_dir / "statement_of_loss.pdf"
        if sol_pdf_path.exists():
            from app.services.ai_service import AIService
            ai_svc = AIService()
            sol = await ai_svc.extract_sol_from_pdf(str(sol_pdf_path), job_id=job_id)
        else:
            sol = StatementOfLoss(line_items=[], overhead_and_profit_included=True)
            
        report = await asyncio.to_thread(reconcile, ev_data, sol, job_id, 0.15)
        bom = report.material_bom
        
        # Fetch Homeowner Info
        job_dict = await asyncio.to_thread(_fetch_job_sync, job_id)
        if not job_dict:
            raise HTTPException(status_code=404, detail="Job not found in database.")
            
        # Generate PO PDF
        pdf_gen = PDFGenerator()
        await pdf_gen.generate_material_po(job_dict, bom, payload.supplier_name, payload.delivery_date)
        
        # Insert Record & Update State
        await asyncio.to_thread(insert_material_order, job_id, payload.supplier_name, payload.delivery_date, bom.model_dump_json())
        await asyncio.to_thread(update_job_status, job_id, JobStatus.MATERIAL_ORDERED)
        
        # Trigger Hot Backup
        bg_tasks.add_task(backup_database)
        
        return {"status": "success"}
    except Exception as e:
        logger.error("material_order_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to process material order")

@router.get("/jobs/{job_id}/docs/po")
def download_po(job_id: str, supplier_name: str):
    """Returns the generated Material Purchase Order PDF."""
    safe_name = supplier_name.replace(' ', '_')
    po_path = FIELD_DOCS_DIR / job_id / f"PO_{safe_name}.pdf"
    
    if not po_path.exists():
        raise HTTPException(status_code=404, detail="Purchase Order not found.")
        
    return FileResponse(path=po_path, filename=f"PO_{safe_name}.pdf", media_type="application/pdf")

@router.get("/jobs/{job_id}/docs/cancellation")
async def download_cancellation(job_id: str):
    """Dynamically generates and returns the Georgia Notice of Cancellation."""
    job_dict = await asyncio.to_thread(_fetch_job_sync, job_id)
    if not job_dict:
        raise HTTPException(status_code=404, detail="Job not found.")
        
    pdf_gen = PDFGenerator()
    pdf_path = await pdf_gen.generate_notice_of_cancellation(job_dict)
    
    return FileResponse(path=pdf_path, filename=f"Notice_of_Cancellation_{job_id[:8]}.pdf", media_type="application/pdf")

@router.get("/jobs/{job_id}/docs/completion")
async def download_completion(job_id: str, completion_date: str):
    """Dynamically generates and returns the Certificate of Completion."""
    job_dict = await asyncio.to_thread(_fetch_job_sync, job_id)
    if not job_dict:
        raise HTTPException(status_code=404, detail="Job not found.")
        
    pdf_gen = PDFGenerator()
    pdf_path = await pdf_gen.generate_certificate_of_completion(job_dict, completion_date)
    
    return FileResponse(path=pdf_path, filename=f"Certificate_of_Completion_{job_id[:8]}.pdf", media_type="application/pdf")

@router.get("/jobs/{job_id}/docs/contingency")
async def download_contingency(job_id: str):
    """Dynamically generates and returns the Insurance Contingency Agreement."""
    job_dict = await asyncio.to_thread(_fetch_job_sync, job_id)
    if not job_dict:
        raise HTTPException(status_code=404, detail="Job not found.")
        
    pdf_gen = PDFGenerator()
    pdf_path = await pdf_gen.generate_contingency_agreement(job_dict)
    
    return FileResponse(path=pdf_path, filename=f"Contingency_Agreement_{job_id[:8]}.pdf", media_type="application/pdf")

class MaterialRow(BaseModel):
    job_id: str
    homeowner_name: str
    supplier_name: str
    delivery_date: str
    materials_ordered: int
    materials_on_site: int
    status: str

class OperationsBrief(BaseModel):
    deliveries_today: int
    crews_today: int
    material_rows: List[MaterialRow]

@router.get("/operations/brief", response_model=OperationsBrief)
def get_operations_brief():
    """Zero-click read projection for operations dashboard."""
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT m.job_id, j.homeowner_name, m.supplier_name, m.delivery_date,
                   j.materials_ordered, j.materials_on_site, j.status AS job_status
            FROM material_orders m
            JOIN jobs j ON m.job_id = j.id
        """)
        m_rows = cursor.fetchall()
        
        material_rows = []
        deliveries_today = 0
        import datetime
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        for r in m_rows:
            d_date = r["delivery_date"]
            if d_date == today_str:
                deliveries_today += 1
            material_rows.append(MaterialRow(
                job_id=r["job_id"],
                homeowner_name=r["homeowner_name"],
                supplier_name=r["supplier_name"],
                delivery_date=d_date,
                materials_ordered=r["materials_ordered"],
                materials_on_site=r["materials_on_site"],
                status=r["job_status"]
            ))
            
        cursor = conn.execute("SELECT COUNT(*) as crews FROM schedule WHERE install_date LIKE ?", (f"{today_str}%",))
        c_row = cursor.fetchone()
        crews_today = c_row["crews"] if c_row else 0
        
        return OperationsBrief(
            deliveries_today=deliveries_today,
            crews_today=crews_today,
            material_rows=material_rows
        )
    finally:
        conn.close()

class AccountingBrief(BaseModel):
    supplemented_rcv_added: str
    qbo_ready_count: int
    rows: List[Dict[str, Any]]

@router.get("/accounting/brief", response_model=AccountingBrief)
def get_accounting_brief():
    """Zero-click read projection for accounting dashboard."""
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT COALESCE(SUM(f.carrier_rcv), 0.0) as total_rcv
            FROM financials f
            JOIN jobs j ON j.id = f.job_id
            WHERE j.status IN ('SUPPLEMENT_GENERATED', 'SUPPLEMENT_APPROVED')
              AND f.qbo_exported = 0
        """)
        rcv_row = cursor.fetchone()
        supplemented_rcv = f"${rcv_row['total_rcv']:,.2f}"
        
        cursor = conn.execute("""
            SELECT j.id, j.invoice_id, j.homeowner_name, j.status,
                   j.acv_received, j.acv_received_at,
                   j.supplement_received, j.supplement_received_at
            FROM jobs j
            JOIN financials f ON j.id = f.job_id
            WHERE j.status IN ('SUPPLEMENT_GENERATED', 'SUPPLEMENT_APPROVED',
                               'INVOICED')
              AND f.qbo_exported = 0
            ORDER BY j.created_at ASC
        """)
        rows = cursor.fetchall()
        
        qbo_ready = len(rows)
        acct_rows = [{
            "job_id": r["id"], "invoice_id": r["invoice_id"], "name": r["homeowner_name"], "status": r["status"],
            "acv_received": r["acv_received"],
            "acv_received_at": r["acv_received_at"],
            "supplement_received": r["supplement_received"],
            "supplement_received_at": r["supplement_received_at"]
        } for r in rows]
        
        return AccountingBrief(
            supplemented_rcv_added=supplemented_rcv,
            qbo_ready_count=qbo_ready,
            rows=acct_rows
        )
    finally:
        conn.close()

from fastapi.responses import StreamingResponse
import csv, io
from app.core.database import atomic_qbo_export
from app.api.auth import verify_accounting

@router.get("/accounting/qbo-export")
async def export_qbo_csv(token=Depends(verify_accounting)):
    """
    Batch QBO export. Queries all eligible jobs (qbo_exported=0),
    generates CSV, sets idempotency lock, returns file download.
    Returns 204 with message if no jobs are pending export.
    """
    batch = atomic_qbo_export()
    if not batch:
        from fastapi import Response
        return Response(
            content="No jobs pending QBO export.",
            status_code=204
        )

    import datetime
    today_dt = datetime.datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")
    due_date_str = (today_dt + datetime.timedelta(days=30)).strftime("%Y-%m-%d")

    output = io.StringIO()
    fieldnames = [
        "*Customer",
        "*InvoiceDate",
        "*DueDate",
        "Terms",
        "Item(Product/Service)",
        "ItemQuantity",
        "ItemRate",
        "ItemAmount",
        "Memo"
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for job in batch:
        qbo_row = {
            "*Customer":             job["homeowner_name"],
            "*InvoiceDate":          today_str,
            "*DueDate":              due_date_str,
            "Terms":                 "Net 30",
            "Item(Product/Service)": "Roofing Services",
            "ItemQuantity":          1,
            "ItemRate":              job["carrier_rcv"],
            "ItemAmount":            job["carrier_rcv"],
            "Memo":                  f"Invoice {job.get('invoice_id','N/A')} | "
                                     f"Claim {job.get('claim_number','N/A')}"
        }
        writer.writerow(qbo_row)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition":
                f"attachment; filename=wickham_qbo_export.csv"
        }
    )

@router.get("/admin/triage", response_class=HTMLResponse)
async def admin_triage_view(request: Request):
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT j.id, j.homeowner_name, j.address_line1,
                   j.status, j.created_at,
                   j.pipeline_error_message,
                   j.ev_total_area_sf, j.ev_predominant_pitch,
                   j.ev_ridge_lf, j.ev_hip_lf,
                   j.ev_valley_lf, j.ev_eaves_lf, j.ev_rakes_lf
            FROM jobs j
            WHERE j.status = 'PENDING_OPERATOR_REVIEW'
            ORDER BY j.created_at ASC
        """)
        stuck_jobs = [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
    return templates.TemplateResponse(
        "admin_triage.html",
        {"request": request, "stuck_jobs": stuck_jobs}
    )

@router.post("/admin/triage/{job_id}/resolve",
             response_class=JSONResponse)
async def admin_triage_resolve(job_id: str, payload: dict = Body(...)):
    """
    Accepts a dict of corrected geometry fields, writes them to
    the jobs table, resets status to EV_PARSED, and enqueues
    the ARQ worker to re-run from the reconcile step.
    """
    allowed_fields = {
        "ev_total_area_sf", "ev_predominant_pitch",
        "ev_ridge_lf", "ev_hip_lf", "ev_valley_lf",
        "ev_eaves_lf", "ev_rakes_lf"
    }
    updates = {k: v for k, v in payload.items()
               if k in allowed_fields and v is not None}
    if not updates:
        raise HTTPException(
            status_code=400,
            detail="No valid fields provided."
        )
    conn = get_connection()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + ["EV_PARSED",
                      None, job_id]
        conn.execute(
            f"""UPDATE jobs
                SET {set_clause},
                    status = ?,
                    pipeline_error_message = ?
                WHERE id = ?""",
            values
        )
        conn.commit()
    finally:
        conn.close()

    # Re-enqueue the ARQ worker for this job (resume=True)
    await request.app.state.redis_pool.enqueue_job(
        "process_supplement_event",
        job_id=job_id,
        resume=True
    )
    return {"status": "queued", "job_id": job_id}

@router.post(
    "/jobs/{job_id}/mark-supplement-sent",
    response_class=JSONResponse
)
async def mark_supplement_sent_route(job_id: str):
    from app.core.database import mark_supplement_sent
    mark_supplement_sent(job_id)
    return {"status": "ok", "job_id": job_id}

@router.post(
    "/accounting/jobs/{job_id}/toggle-payment",
    response_class=JSONResponse
)
async def toggle_payment(request: Request, job_id: str, payload: dict = Body(...)):
    flag = payload.get("flag")
    from app.core.database import toggle_payment_flag
    result = toggle_payment_flag(job_id, flag)
    if result.get("commission_triggered"):
        await request.app.state.redis_pool.enqueue_job(
            "process_commission",
            job_id=job_id
        )
    return result

@router.post(
    "/jobs/{job_id}/approve-supplement",
    response_class=JSONResponse
)
async def approve_supplement(
    job_id: str, payload: dict = Body(default={})
):
    """
    Operator gate: transitions AWAITING_CARRIER_RESPONSE
    → SUPPLEMENT_APPROVED.
    Triggers a WebSocket broadcast to alert Scott and Debi.
    """
    note = payload.get("note", "Approved by operator.")
    from app.core.database import update_job_status, JobStatus
    try:
        update_job_status(
            job_id, JobStatus.SUPPLEMENT_APPROVED, note
        )
        # Broadcast over existing office WebSocket
        from app.core.notifications import notifier
        await notifier.broadcast({"type": "supplement_approved",
                                  "job_id": job_id})
        return {"status": "approved", "job_id": job_id}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("approve_supplement_failed",
                     job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post(
    "/jobs/{job_id}/deny-supplement",
    response_class=JSONResponse
)
async def deny_supplement(request: Request, job_id: str,
                           payload: dict = Body(...)):
    """
    Operator gate: transitions AWAITING_CARRIER_RESPONSE
    → SUPPLEMENT_DENIED.
    Stores denial text and enqueues the rebuttal ARQ worker.
    """
    denial_text = payload.get("denial_text")
    denial_pdf_doc_id = payload.get("denial_pdf_doc_id")
    if not denial_text and not denial_pdf_doc_id:
        raise HTTPException(
            status_code=400,
            detail="Must provide denial_text or denial_pdf_doc_id."
        )
    note = f"Denied. Reason: {(denial_text or '')[:200]}"
    from app.core.database import update_job_status, JobStatus
    try:
        update_job_status(
            job_id, JobStatus.SUPPLEMENT_DENIED, note
        )
        # Enqueue rebuttal worker
        await request.app.state.redis_pool.enqueue_job(
            "process_rebuttal",
            job_id=job_id,
            denial_text=denial_text,
            denial_pdf_doc_id=denial_pdf_doc_id
        )
        return {"status": "denied_rebuttal_queued",
                "job_id": job_id}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("deny_supplement_failed",
                     job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/jobs/{job_id}/docs/rebuttal",
    response_class=FileResponse
)
async def download_rebuttal(job_id: str):
    from app.core.database import get_job_documents
    from fastapi.responses import FileResponse
    docs = get_job_documents(job_id,
                             file_type="REBUTTAL_PDF")
    if not docs:
        raise HTTPException(404, "No rebuttal PDF found.")
    path = docs[0]["storage_path"]
    if not Path(path).exists():
        raise HTTPException(404, "Rebuttal PDF file missing.")
    return FileResponse(
        path,
        filename=f"Rebuttal_{job_id[:8]}.pdf",
        media_type="application/pdf"
    )

@router.get("/accounting/commissions-ready", response_class=JSONResponse)
def get_commissions_ready():
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT id as job_id, invoice_id, homeowner_name, canvasser_name, commission_generated_at
            FROM jobs
            WHERE commission_ready = 1
            ORDER BY commission_generated_at DESC
        """)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

@router.get("/jobs/{job_id}/docs/commission", response_class=FileResponse)
def download_commission(job_id: str):
    from app.core.database import get_job_documents
    docs = get_job_documents(job_id, file_type="COMMISSION_PDF")
    if not docs:
        raise HTTPException(404, "No commission statement found.")
    path = docs[0]["storage_path"]
    if not Path(path).exists():
        raise HTTPException(404, "Commission PDF missing.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"Commission_Statement_{job_id[:8]}.pdf"
    )

@router.post("/jobs/{job_id}/escalate")
async def queue_escalation(request: Request, job_id: str):
    await request.app.state.redis_pool.enqueue_job(
        "process_escalation",
        job_id=job_id
    )
    return {"status": "escalation_queued"}

@router.get("/jobs/{job_id}/docs/escalation", response_class=FileResponse)
def download_escalation(job_id: str):
    from app.core.database import get_job_documents
    docs = get_job_documents(job_id, file_type="ESCALATION_PDF")
    if not docs:
        raise HTTPException(404, "No escalation letter found.")
    path = docs[0]["storage_path"]
    if not Path(path).exists():
        raise HTTPException(404, "Escalation PDF missing.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"Escalation_Demand_{job_id[:8]}.pdf"
    )
