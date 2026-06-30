"""
Inspection Vision Engine orchestrator.

Processes a batch of roof photos for a single InspectionJob by:
1. Iterating photos SEQUENTIALLY (no parallelism — free-tier quota protection).
2. Uploading each photo via Gemini File API.
3. Polling until processing completes.
4. Running multimodal damage analysis with the flat PhotoAnalysis schema.
5. Immediately deleting the remote file for privacy and quota management.
6. Providing a Pillow-based image resizer for downstream ReportLab PDF embedding.

This worker follows the same async-to-thread pattern as supplement_processor.py.
"""

import io
import time
import structlog
from pathlib import Path

from PIL import Image as PILImage

from app.services.ai_service import AIService
from app.core.inspection_models import InspectionJob
from app.core.temp_manager import create_temp_file
from app.core.cache import get_cached_analysis, set_cached_analysis

logger = structlog.get_logger("app.workers.inspection_processor")


def resize_for_pdf(src: Path, max_width: int = 800) -> io.BytesIO:
    """
    Downsample an image to a maximum width for safe ReportLab PDF embedding.

    Full-resolution field photos (4000x3000px+) will cause Out-Of-Memory
    crashes when ReportLab builds the platypus story. This function
    produces a lightweight PNG buffer that ReportLab can consume via
    ImageReader without OOM risk.

    Args:
        src: Path to the source image file on disk.
        max_width: Maximum pixel width for the output. Default 800.

    Returns:
        A BytesIO buffer containing the resized PNG image, seeked to 0.
    """
    with PILImage.open(src) as img:
        # Convert HEIC/other modes to RGB for PNG compatibility
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), PILImage.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf


def resize_for_ai(src: Path, max_width: int = 1600) -> str:
    """
    Downsample a field photo for Gemini File API upload.

    Reduces 4000px+ raw field photos to 1600px to save network bandwidth
    and API processing time, while preserving enough detail for forensic
    damage analysis.

    Writes the output to a managed temporary file that will be cleaned up
    on process exit by temp_manager.

    Args:
        src: Path to the source image file on disk.
        max_width: Maximum pixel width for the output. Default 1600.

    Returns:
        Absolute filepath to the downscaled temporary JPEG file.
    """
    with PILImage.open(src) as img:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), PILImage.LANCZOS)

        temp_path = create_temp_file(suffix=".jpg")
        img.save(temp_path, format="JPEG", quality=85)
        return temp_path


async def process_inspection(ctx: dict, job: InspectionJob) -> InspectionJob:
    """
    Process all photos in an InspectionJob through the Gemini Vision Engine.

    Iterates SEQUENTIALLY to respect free-tier rate limits. Each photo
    goes through the full lifecycle: upload → poll → analyze → delete.

    The _call_with_backoff wrapper on AIService handles 429 retries
    with exponential backoff + jitter.

    Args:
        ctx: Worker context dict (for future CRM client injection).
        job: InspectionJob with photos populated by get_stable_photos().

    Returns:
        The same InspectionJob with analyses populated.
    """
    import asyncio

    log = logger.bind(job_id=job.job_id, total_photos=len(job.photos))
    log.info("inspection_processing_started")

    ai = AIService()

    def _process_all():
        for idx, photo in enumerate(job.photos):
            photo_log = log.bind(
                photo=photo.filepath.name,
                index=idx + 1,
                total=len(job.photos),
            )

            # Check cache first (EPIC 1)
            cached = get_cached_analysis(job.job_id, photo.sha256)
            if cached:
                cached.filename = photo.filepath.name
                job.analyses.append(cached)
                photo_log.info("photo_analysis_cache_hit", damage=cached.damage_detected)
                continue

            photo_log.info("photo_processing_started")

            uploaded_name = None
            try:
                # 0. Dual-Image Scaling: Create 1600px temporary file for AI
                photo_log.debug("downscaling_for_ai")
                ai_file_path = resize_for_ai(photo.filepath, max_width=1600)

                # 1. Upload to Gemini File API
                uploaded_file = ai.client.files.upload(file=ai_file_path)
                uploaded_name = uploaded_file.name
                photo_log.debug("photo_uploaded", remote_name=uploaded_name)

                # 2. Poll until processing completes
                file_info = ai.client.files.get(name=uploaded_name)
                while file_info.state.name == "PROCESSING":
                    time.sleep(2)
                    file_info = ai.client.files.get(name=uploaded_name)

                if file_info.state.name == "FAILED":
                    photo_log.error("photo_processing_failed_on_server")
                    continue

                # 3. Analyze with backoff protection
                analysis = ai._call_with_backoff(ai.analyze_roof_photo, file_info)
                analysis.filename = photo.filepath.name
                job.analyses.append(analysis)

                # Cache the successful result (EPIC 1)
                set_cached_analysis(job.job_id, photo.sha256, analysis)

                photo_log.info(
                    "photo_analysis_complete",
                    damage=analysis.damage_detected,
                    severity=analysis.severity.value,
                    confidence=analysis.confidence,
                )

            except RuntimeError as e:
                # Rate limit exhausted after max retries
                photo_log.error("photo_analysis_rate_limited", error=str(e))
                continue
            except Exception as e:
                photo_log.error("photo_analysis_unexpected_error", error=str(e))
                continue
            finally:
                # 4. Cleanup: immediately delete from Google's servers
                if uploaded_name:
                    try:
                        ai.client.files.delete(name=uploaded_name)
                        photo_log.debug("remote_file_deleted", remote_name=uploaded_name)
                    except Exception:
                        photo_log.warning("remote_file_cleanup_failed", remote_name=uploaded_name)

    await asyncio.to_thread(_process_all)

    log.info(
        "inspection_processing_complete",
        analyzed=len(job.analyses),
        damage_found=job.damage_count,
        actionable=job.has_actionable_damage,
    )
    return job
