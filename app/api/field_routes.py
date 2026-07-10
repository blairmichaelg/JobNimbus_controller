"""
FastAPI HTTP surface for Field UX (iPad LAN decoupling).

These endpoints allow the field inspectors to:
1. Upload photos directly from the iPad over LAN (bypassing Google Drive sync).
2. Retrieve the InspectionJob summary (using cached Gemini analyses).
3. Capture and save digital signatures as physical images for the PDF appendix.
"""

import base64
import io
import structlog
import uuid
import json
import os
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from pydantic import BaseModel, Field

from app.core.inspection_models import get_stable_photos, InspectionJob
from app.core.cache import get_cached_analyses_for_job
from app.core.database import get_connection, update_job_status
from app.config import verify_field_token
from app.core.upload_utils import stream_upload_safely

logger = structlog.get_logger("app.api.field_routes")

router = APIRouter(prefix="/api/field", tags=["field_ux"], dependencies=[Depends(verify_field_token)])

# Base directories (created on startup)
FIELD_PHOTOS_DIR = Path("field_photos")
FIELD_DOCS_DIR = Path("field_docs")
SIGNED_AGREEMENTS_DIR = Path("signed_agreements")

class LeadIntakePayload(BaseModel):
    homeowner_name: str
    address_line1: str
    city: str
    state: str
    postal_code: str
    phone: str
    email: str | None = None
    claim_number: str | None = None
    insurer_name: str | None = None
    job_type: str = Field(default="INSURANCE")

class SignaturePayload(BaseModel):
    job_id: str = Field(..., description="JobNimbus entity ID")
    signature_base64: str = Field(..., description="Data URI from HTML5 Canvas (data:image/png;base64,...)")
    ip_address: str | None = Field(None, description="IP address of the device capturing the signature")
    timestamp: str | None = Field(None, description="ISO8601 timestamp of signature capture")
    user_agent: str | None = Field(None, description="User Agent of the device capturing the signature")

class ContingencySignaturePayload(BaseModel):
    signature_base64: str = Field(..., description="Data URI from HTML5 Canvas")
    signer_name: str = Field(..., description="Name of the person signing")
    ip_address: str | None = Field(None, description="IP address of the device capturing the signature")
    user_agent: str | None = Field(None, description="User Agent of the device capturing the signature")

@router.post("/jobs")
def create_new_job(payload: LeadIntakePayload):
    """
    Intake hook for new leads. Replaces JobNimbus lead creation.
    Generates UUID, creates directories, and initializes local SQLite record.
    """
    job_id = str(uuid.uuid4())
    
    # Insert into database
    conn = get_connection()
    try:
        initial_history = [{
            "status": "LEAD_CAPTURED",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "note": "Initial canvasser intake via Truck Server"
        }]
        
        conn.execute('''
            INSERT INTO jobs (
                id, homeowner_name, address_line1, city, state, postal_code, 
                phone, email, claim_number, insurer_name, status, status_history, job_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job_id, payload.homeowner_name, payload.address_line1, payload.city,
            payload.state, payload.postal_code, payload.phone, payload.email,
            payload.claim_number, payload.insurer_name, "LEAD_CAPTURED",
            json.dumps(initial_history), payload.job_type
        ))
        conn.commit()
    except Exception as e:
        logger.error("lead_intake_db_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Database insertion failed")
    finally:
        conn.close()

    # Create local directories
    (FIELD_PHOTOS_DIR / job_id).mkdir(parents=True, exist_ok=True)
    (FIELD_DOCS_DIR / job_id).mkdir(parents=True, exist_ok=True)
    
    logger.info("new_lead_captured", job_id=job_id, homeowner=payload.homeowner_name)
    return {"status": "success", "job_id": job_id}


@router.post("/jobs/{job_id}/photos")
async def upload_field_photo(job_id: str, file: UploadFile = File(...)):
    """
    Accept direct photo uploads from the iPad over LAN.
    Stores files in field_photos/{job_id}/ for downstream processing.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing")

    if file.content_type not in ["image/jpeg", "image/png"]:
        raise HTTPException(status_code=400, detail="Invalid image format. Must be JPEG or PNG.")

    job_dir = FIELD_PHOTOS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    safe_name = Path(file.filename).name
    file_path = job_dir / safe_name

    try:
        await stream_upload_safely(file, file_path)
        logger.info("field_photo_uploaded", job_id=job_id, filename=safe_name, size=getattr(file, "size", 0))
        return {"status": "success", "filename": safe_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("field_photo_upload_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save photo")


@router.get("/jobs/{job_id}/inspection", response_model=InspectionJob)
def get_inspection_summary(job_id: str):
    """
    Retrieve the full InspectionJob summary.
    Constructs the job by scanning the local field_photos/{job_id} directory
    and reading available analyses directly from the SQLite cache.
    """
    job_dir = FIELD_PHOTOS_DIR / job_id

    # Get local photos if directory exists
    photos = []
    if job_dir.exists() and job_dir.is_dir():
        # Settle seconds = 0 for direct HTTP uploads (no Drive sync delay)
        photos = get_stable_photos(job_dir, settle_seconds=0)

    # Retrieve all cached analyses for this job
    analyses = get_cached_analyses_for_job(job_id)

    job = InspectionJob(
        job_id=job_id,
        property_address="Unknown Address (Pending Sync)",  # Would be pulled from CRM in full impl
        inspection_date=datetime.now(),
        photos=photos,
        analyses=analyses,
    )

    logger.info(
        "inspection_summary_retrieved",
        job_id=job_id,
        photos_count=job.total_photos,
        analyses_count=len(job.analyses),
    )
    return job





@router.post("/jobs/{job_id}/contingency-sign")
async def contingency_sign(job_id: str, payload: ContingencySignaturePayload):
    """
    Handle E-Signature for Contingency Agreements.
    Saves PNG, generates PDF, logs agreement, and updates status.
    """
    try:
        header, encoded = payload.signature_base64.split(",", 1) if "," in payload.signature_base64 else ("", payload.signature_base64)
        image_bytes = base64.b64decode(encoded)
        
        SIGNED_AGREEMENTS_DIR.mkdir(parents=True, exist_ok=True)
        sig_file_path = SIGNED_AGREEMENTS_DIR / f"{job_id}_contingency_sig.png"
        sig_file_path.write_bytes(image_bytes)
        
        conn = get_connection()
        try:
            cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            job_row = cursor.fetchone()
            if not job_row:
                raise HTTPException(status_code=404, detail="Job not found")
            job_dict = dict(job_row)
        finally:
            conn.close()

        from app.services.pdf_generator import PDFGenerator
        pdf_gen = PDFGenerator()
        pdf_path = await pdf_gen.generate_contingency_pdf(
            job_dict, 
            str(sig_file_path), 
            payload.signer_name, 
            payload.ip_address or "Unknown IP"
        )
        
        conn = get_connection()
        try:
            agreement_id = str(uuid.uuid4())
            ts = datetime.utcnow().isoformat() + "Z"
            conn.execute('''
                INSERT INTO job_agreements (id, job_id, type, pdf_path, signature_image_path, signed_at, signed_by_name, signed_by_ip, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (agreement_id, job_id, "CONTINGENCY", pdf_path, str(sig_file_path), ts, payload.signer_name, payload.ip_address, payload.user_agent))
            conn.commit()
        finally:
            conn.close()
            
        update_job_status(job_id, "CONTINGENCY_SIGNED", f"Contingency signed by {payload.signer_name}")
        
        logger.info("contingency_signed_and_generated", job_id=job_id, agreement_id=agreement_id)
        return {"status": "success", "pdf_path": Path(pdf_path).name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("contingency_sign_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to process contingency signature")
