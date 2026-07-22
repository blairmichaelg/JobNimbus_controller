"""
FastAPI HTTP surface for Field UX (iPad LAN decoupling).

These endpoints allow the field inspectors to:
1. Upload photos directly from the iPad over LAN (bypassing Google Drive sync).
2. Retrieve the InspectionJob summary (using cached Gemini analyses).
3. Capture and save digital signatures as physical images for the PDF appendix.
"""

import asyncio
import base64
import io
import structlog
import uuid
import json
from pathlib import Path
from datetime import datetime
from PIL import Image

from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Request, BackgroundTasks
from app.api.auth import get_current_role
from app.services.field_access import assert_field_rep_owns_job
from app.services.rate_limit import check_rate_limit
from app.core.climate_lookup import is_ice_barrier_required
from pydantic import BaseModel, Field

from app.core.inspection_models import get_stable_photos, InspectionJob
from app.core.cache import get_cached_analyses_for_job
from app.core.database import get_connection, update_job_status
from app.api.auth import verify_field, get_current_claims
from app.core.upload_utils import stream_upload_safely
from app.core.notifications import notifier

logger = structlog.get_logger("app.api.field_routes")
router = APIRouter(prefix="/api/field", tags=["field_ux"], dependencies=[Depends(verify_field)])

# Base directories (created on startup)
FIELD_PHOTOS_DIR = Path("field_photos")
from app.config import FIELD_DOCS_DIR
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
    loss_date: str | None = None
    canvasser_name: str | None = None

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

class FlagResolutionPayload(BaseModel):
    quantity_delta: float = Field(..., description="The corrected, manually determined quantity")
    resolution_note: str = Field(..., description="Audit note explaining the manual override")

def _sync_create_new_job(job_id: str, inv_id: str, payload: LeadIntakePayload, ice_barrier: bool | None, canvasser_name: str, canvasser_rep_id: str | None = None):
    conn = get_connection()
    try:
        initial_history = [{
            "status": "LEAD_CAPTURED",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "note": "Initial canvasser intake via Truck Server"
        }]
        
        conn.execute('''
            INSERT INTO jobs (
                id, invoice_id, homeowner_name, address_line1, city, state, postal_code, 
                phone, email, claim_number, insurer_name, status, status_history, job_type,
                ice_barrier_required, jurisdiction_code_version, canvasser_name, canvasser_rep_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job_id, inv_id, payload.homeowner_name, payload.address_line1, payload.city,
            payload.state, payload.postal_code, payload.phone, payload.email,
            payload.claim_number, payload.insurer_name, "LEAD_CAPTURED",
            json.dumps(initial_history), payload.job_type,
            ice_barrier, "2021_IRC", canvasser_name, canvasser_rep_id
        ))
        
        if payload.loss_date:
            sv_id = str(uuid.uuid4())
            conn.execute('''
                INSERT INTO storm_verifications (id, job_id, loss_date, event_type, begin_lat, begin_lon, match_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (sv_id, job_id, payload.loss_date, 'Unknown', 0.0, 0.0, 'Pending'))
            
        conn.commit()
    finally:
        conn.close()


@router.post("/jobs")
async def create_new_job(
    payload: LeadIntakePayload,
    request: Request,
    role: str = Depends(verify_field),
    claims: dict = Depends(get_current_claims),
):
    """
    Intake hook for new leads. Replaces JobNimbus lead creation.
    Generates UUID, creates directories, and initializes local SQLite record.
    """
    job_id = str(uuid.uuid4())
    
    # Determine climate requirements
    ice_barrier = is_ice_barrier_required(payload.state)
    
    # Generate invoice ID
    from app.core.database import generate_invoice_id
    inv_id = generate_invoice_id()

    # Resolve canvasser identity from JWT claims first, then payload fallback
    canvasser_name = (
        claims.get("rep_name")           # from JWT (field rep identity)
        or (payload.canvasser_name or "").strip()  # manual override in payload
        or "Unassigned"                   # last resort
    )
    rep_id = claims.get("rep_id")
    
    # Insert into database using background thread
    try:
        await asyncio.to_thread(_sync_create_new_job, job_id, inv_id, payload, ice_barrier, canvasser_name, rep_id)
        
        await notifier.broadcast({
            "type": "new_lead",
            "job": {
                "id": job_id,
                "homeowner_name": payload.homeowner_name,
                "address_line1": payload.address_line1,
                "city": payload.city,
                "state": payload.state,
                "status": "LEAD_CAPTURED",
                "ice_barrier_required": ice_barrier
            }
        })
    except Exception as e:
        logger.error("lead_intake_db_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Database insertion failed")

    # Create local directories
    (FIELD_PHOTOS_DIR / job_id).mkdir(parents=True, exist_ok=True)
    (FIELD_DOCS_DIR / job_id).mkdir(parents=True, exist_ok=True)
    
    # Fork retail jobs to retail quote worker
    job_type = payload.job_type
    if job_type == "RETAIL":
        await request.app.state.redis_pool.enqueue_job(
            "process_retail_quote", job_id=job_id
        )

    logger.info("new_lead_captured", job_id=job_id, invoice_id=inv_id, homeowner=payload.homeowner_name)
    return {"status": "success", "job_id": job_id}


@router.post("/jobs/{job_id}/photos")
async def upload_field_photo(job_id: str, file: UploadFile = File(...), claims: dict = Depends(get_current_claims)):
    assert_field_rep_owns_job(claims, job_id)
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
        await stream_upload_safely(
            file, 
            file_path, 
            max_bytes=15 * 1024 * 1024, 
            allowed_magic_bytes=[b"\xFF\xD8\xFF", b"\x89PNG\r\n\x1A\n"]
        )
        logger.info("field_photo_uploaded", job_id=job_id, filename=safe_name, size=getattr(file, "size", 0))
        return {"status": "success", "filename": safe_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("field_photo_upload_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save photo")


@router.get("/jobs/{job_id}/inspection", response_model=InspectionJob)
async def get_inspection_summary(job_id: str, claims: dict = Depends(get_current_claims)):
    assert_field_rep_owns_job(claims, job_id)
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
        photos = await asyncio.to_thread(get_stable_photos, job_dir, 0)

    # Retrieve all cached analyses for this job
    analyses = await asyncio.to_thread(get_cached_analyses_for_job, job_id)

    # Fetch real address and inspector from the jobs table
    property_address = "Unknown Address"
    inspector_name = "Wickham Roofing LLC"
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT address_line1, city, state, postal_code, inspector_name FROM jobs WHERE id = ?",
            (job_id,)
        )
        row = cursor.fetchone()
        if row:
            property_address = f"{row['address_line1']}, {row['city']}, {row['state']} {row['postal_code']}"
            if row["inspector_name"]:
                inspector_name = row["inspector_name"]
    finally:
        conn.close()

    job = InspectionJob(
        job_id=job_id,
        property_address=property_address,
        inspection_date=datetime.now(),
        inspector_name=inspector_name,
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


@router.post("/jobs/{job_id}/resume-supplement", status_code=202, dependencies=[Depends(check_rate_limit)])
async def resume_supplement(job_id: str, request: Request, background_tasks: BackgroundTasks, role: str = Depends(get_current_role), claims: dict = Depends(get_current_claims)):
    assert_field_rep_owns_job(claims, job_id)
    """
    Resumes a halted supplement pipeline (e.g. from PENDING_MANUAL_REVIEW).
    Skips parsing and gating, and goes straight to Narrative/PDF generation.
    """
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id format. Must be a valid UUID.")

    redis = getattr(request.app.state, "redis_pool", None)
    if not redis:
        raise HTTPException(status_code=503, detail="Redis connection unavailable")

    # Enqueue ARQ task with resume=True
    await redis.enqueue_job("process_supplement_event", job_id, None, None, resume=True, role=role)
    
    return {"status": "accepted", "job_id": job_id, "message": "Supplement resume processing started."}

def _sync_resolve_flag(job_id: str, flag_id: str, payload: FlagResolutionPayload):
    conn = get_connection()
    try:
        # Verify the flag exists and belongs to the job
        cursor = conn.execute("SELECT id FROM supplement_flags WHERE id = ? AND job_id = ?", (flag_id, job_id))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Flag not found or does not belong to this job.")
        
        # Update the flag
        audit_note = f"RESOLVED: {payload.resolution_note}"
        conn.execute('''
            UPDATE supplement_flags
            SET quantity_delta = ?, notes = ?
            WHERE id = ?
        ''', (payload.quantity_delta, audit_note, flag_id))
        conn.commit()
    finally:
        conn.close()

@router.patch("/jobs/{job_id}/flags/{flag_id}", status_code=200)
async def resolve_flag(job_id: str, flag_id: str, payload: FlagResolutionPayload, claims: dict = Depends(get_current_claims)):
    assert_field_rep_owns_job(claims, job_id)
    """
    Resolves a flag that was marked for manual review.
    Updates the quantity and adds a resolution note.
    """
    try:
        uuid.UUID(job_id)
        uuid.UUID(flag_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id or flag_id format. Must be a valid UUID.")

    await asyncio.to_thread(_sync_resolve_flag, job_id, flag_id, payload)
        
    return {"status": "success", "flag_id": flag_id, "message": "Flag resolved successfully."}


def _sync_fetch_job_contingency(job_id: str):
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        job_row = cursor.fetchone()
        if not job_row:
            raise HTTPException(status_code=404, detail="Job not found")
        return dict(job_row)
    finally:
        conn.close()

def _sync_process_image(encoded_b64: str, job_id: str) -> Path:
    image_bytes = base64.b64decode(encoded_b64)
    image = Image.open(io.BytesIO(image_bytes))
    image.verify()  # Verify it's a valid image
    
    # Re-open for actual processing/saving since verify() leaves the file pointer at the end
    image = Image.open(io.BytesIO(image_bytes))
    
    # Enforce format and re-save cleanly
    if image.format not in ["PNG", "JPEG"]:
        raise ValueError("Unsupported image format")
        
    SIGNED_AGREEMENTS_DIR.mkdir(parents=True, exist_ok=True)
    sig_file_path = SIGNED_AGREEMENTS_DIR / f"{job_id}_contingency_sig.png"
    
    # Convert to RGBA for PNG compatibility and save
    image = image.convert("RGBA")
    image.save(sig_file_path, format="PNG", optimize=True)
    return sig_file_path

def _sync_insert_agreement(agreement_id: str, job_id: str, pdf_path: str, sig_file_path: str, ts: str, signer_name: str, ip_address: str | None, user_agent: str | None):
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO job_agreements (id, job_id, type, pdf_path, signature_image_path, signed_at, signed_by_name, signed_by_ip, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (agreement_id, job_id, "CONTINGENCY", pdf_path, sig_file_path, ts, signer_name, ip_address, user_agent))
        conn.commit()
    finally:
        conn.close()

@router.post("/jobs/{job_id}/contingency-sign")
async def contingency_sign(job_id: str, payload: ContingencySignaturePayload, claims: dict = Depends(get_current_claims)):
    assert_field_rep_owns_job(claims, job_id)
    """
    Handle E-Signature for Contingency Agreements.
    Saves PNG, generates PDF, logs agreement, and updates status.
    """
    # Strictly validate job_id format to prevent path traversal
    try:
        uuid_obj = uuid.UUID(job_id)
        job_id = str(uuid_obj)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id format. Must be a valid UUID.")

    if len(payload.signature_base64) > 2_000_000:
        raise HTTPException(status_code=413, detail="Payload too large. Maximum size is 2MB.")
        
    if not payload.signature_base64.startswith("data:image/png;base64,"):
        raise HTTPException(status_code=400, detail="Invalid signature format. Must be a PNG data URI.")
        
    try:
        job_dict = await asyncio.to_thread(_sync_fetch_job_contingency, job_id)

        header, encoded = payload.signature_base64.split(",", 1)
        
        # Verify and sanitize the image using Pillow before saving to disk
        try:
            sig_file_path = await asyncio.to_thread(_sync_process_image, encoded, job_id)
        except Exception as e:
            logger.error("signature_image_verification_failed", error=str(e))
            raise HTTPException(status_code=400, detail="Invalid or corrupt image data")

        from app.services.pdf_generator import PDFGenerator
        pdf_gen = PDFGenerator()
        pdf_path = await pdf_gen.generate_contingency_pdf(
            job_dict, 
            str(sig_file_path), 
            payload.signer_name, 
            payload.ip_address or "Unknown IP"
        )
        
        agreement_id = str(uuid.uuid4())
        ts = datetime.utcnow().isoformat() + "Z"
        await asyncio.to_thread(_sync_insert_agreement, agreement_id, job_id, pdf_path, str(sig_file_path), ts, payload.signer_name, payload.ip_address, payload.user_agent)
            
        await asyncio.to_thread(update_job_status, job_id, "CONTINGENCY_SIGNED", f"Contingency signed by {payload.signer_name}")
        
        await notifier.broadcast({
            "type": "contingency_signed",
            "job": {
                "id": job_id,
                "signer_name": payload.signer_name,
                "status": "CONTINGENCY_SIGNED"
            }
        })
        
        logger.info("contingency_signed_and_generated", job_id=job_id, agreement_id=agreement_id)
        return {"status": "success", "pdf_path": Path(pdf_path).name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("contingency_sign_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to process contingency signature")
