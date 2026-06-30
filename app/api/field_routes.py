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
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from pydantic import BaseModel, Field

from app.core.inspection_models import get_stable_photos, InspectionJob
from app.core.cache import get_cached_analyses_for_job

logger = structlog.get_logger("app.api.field_routes")

router = APIRouter(prefix="/api/field", tags=["field_ux"])

# Base directories (created on startup)
FIELD_PHOTOS_DIR = Path("field_photos")
SIGNED_AGREEMENTS_DIR = Path("signed_agreements")


class SignaturePayload(BaseModel):
    job_id: str = Field(..., description="JobNimbus entity ID")
    signature_base64: str = Field(..., description="Data URI from HTML5 Canvas (data:image/png;base64,...)")


@router.post("/jobs/{job_id}/photos")
async def upload_field_photo(job_id: str, file: UploadFile = File(...)):
    """
    Accept direct photo uploads from the iPad over LAN.
    Stores files in field_photos/{job_id}/ for downstream processing.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing")

    job_dir = FIELD_PHOTOS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    safe_name = Path(file.filename).name
    file_path = job_dir / safe_name

    try:
        content = await file.read()
        file_path.write_bytes(content)
        logger.info("field_photo_uploaded", job_id=job_id, filename=safe_name, bytes=len(content))
        return {"status": "success", "filename": safe_name}
    except Exception as e:
        logger.error("field_photo_upload_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save photo")


@router.get("/jobs/{job_id}/inspection", response_model=InspectionJob)
async def get_inspection_summary(job_id: str):
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


@router.post("/sign")
async def capture_signature(payload: SignaturePayload):
    """
    Accept a base64 HTML5 canvas signature and save it as a physical PNG.
    Used later by the ReportLab Evidence Grid for contract attachment.
    """
    try:
        # Strip the Data URI scheme prefix if present
        header, encoded = payload.signature_base64.split(",", 1) if "," in payload.signature_base64 else ("", payload.signature_base64)
        
        image_bytes = base64.b64decode(encoded)
        
        SIGNED_AGREEMENTS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = SIGNED_AGREEMENTS_DIR / f"{payload.job_id}_signature.png"
        
        file_path.write_bytes(image_bytes)
        
        logger.info("signature_captured", job_id=payload.job_id, path=str(file_path))
        return {"status": "success", "file": file_path.name}
    except Exception as e:
        logger.error("signature_capture_failed", job_id=payload.job_id, error=str(e))
        raise HTTPException(status_code=400, detail="Invalid signature payload")
