"""
Pydantic V2 models for the V3 Inspection Vision Engine.

These models enforce the data contract between the Google Drive sync folder,
the Gemini 2.5 Flash multimodal analysis, and the ReportLab PDF evidence grid.

Key design decisions:
- PhotoAnalysis is INTENTIONALLY FLAT (no nesting). Gemini's response_schema
  throws 400 Bad Request on deeply nested Pydantic models.
- InspectionPhoto validates file extensions at parse time to reject non-image files.
- get_stable_photos() implements a dual guard: a 10-second mtime staleness check
  (Google Drive writes temp files during sync) and SHA256 deduplication to prevent
  reprocessing photos across multiple pipeline runs.
"""

import hashlib
import os
import time
import structlog
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

logger = structlog.get_logger("app.core.inspection_models")

# Supported image extensions for roof photo ingestion.
ALLOWED_IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


# ── Enums ──────────────────────────────────────────────────────────────────────


class DamageType(str, Enum):
    """Primary damage classification detected by Gemini vision analysis."""
    HAIL = "hail"
    WIND = "wind"
    MECHANICAL = "mechanical"
    AGING = "aging"
    NONE = "none"


class Severity(str, Enum):
    """Damage severity scale used for claim triage."""
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"


# ── Gemini Structured Output Schema ───────────────────────────────────────────


class PhotoAnalysis(BaseModel):
    """
    Flat Pydantic schema enforced on Gemini's structured JSON output.

    This model is passed directly to `response_schema` in the GenAI SDK config.
    It MUST remain flat (no nested BaseModel children) to avoid 400 errors
    from the Gemini structured output API.

    The boolean forensic flags provide deterministic, machine-readable damage
    indicators. The forensic_narrative provides the adjuster-facing prose.
    The LLM fills this schema — it never touches downstream math.
    """

    filename: str = Field(
        description="Original filename of the analyzed photo."
    )
    damage_detected: bool = Field(
        description="True if any hail or wind damage is visible in the photo."
    )
    damage_type: DamageType = Field(
        description="Primary damage classification: hail, wind, mechanical, aging, or none."
    )
    severity: Severity = Field(
        description="Severity of the detected damage: none, minor, moderate, or severe."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model confidence score between 0.0 and 1.0."
    )

    # Forensic boolean flags — structured indicators for evidence grid
    hail_hits_visible: bool = Field(
        default=False,
        description="True if distinct circular hail impact marks are visible on shingles."
    )
    crease_marks: bool = Field(
        default=False,
        description="True if wind-lifted shingle crease lines are visible."
    )
    granule_loss: bool = Field(
        default=False,
        description="True if significant granule displacement is visible on shingle surfaces."
    )
    exposed_fiberglass: bool = Field(
        default=False,
        description="True if the fiberglass mat is exposed on any shingle."
    )

    forensic_narrative: str = Field(
        description=(
            "2-3 sentence technical forensic description of visible damage indicators. "
            "Written as expert testimony suitable for an insurance adjuster review."
        )
    )


# ── Photo Ingestion Models ────────────────────────────────────────────────────


class InspectionPhoto(BaseModel):
    """
    Metadata for a single photo file before Gemini analysis.

    Validates that the file extension is a supported image format at parse time.
    The sha256 hash is computed during ingestion by get_stable_photos() and used
    to prevent duplicate processing across pipeline runs.
    """

    filepath: Path
    captured_at: datetime | None = None
    sha256: str | None = None

    @field_validator("filepath")
    @classmethod
    def validate_image_extension(cls, v: Path) -> Path:
        """
        Validate Image Extension functionality.
        
        Args:
                cls (Any): cls parameter.
                v (Path): v parameter.
        
        Returns:
            Path: The resulting output.
        """
        if v.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError(
                f"Unsupported image format '{v.suffix}'. "
                f"Allowed: {ALLOWED_IMAGE_EXTENSIONS}"
            )
        return v


class InspectionJob(BaseModel):
    """
    Top-level container for a complete roof inspection batch.

    Aggregates raw photos and their corresponding Gemini analyses.
    The computed properties provide quick triage metrics for the
    inspection processor without iterating the full list.
    """

    job_id: str
    property_address: str
    inspection_date: datetime
    inspector_name: str = "Wickham Roofing LLC"
    photos: list[InspectionPhoto] = []
    analyses: list[PhotoAnalysis] = []

    @property
    def total_photos(self) -> int:
        """Total number of photos ingested for this job."""
        return len(self.photos)

    @property
    def damage_count(self) -> int:
        """Number of photos where damage was positively detected."""
        return sum(1 for a in self.analyses if a.damage_detected)

    @property
    def has_actionable_damage(self) -> bool:
        """True if any photo shows moderate or severe damage — triggers claim filing."""
        return any(
            a.damage_detected and a.severity in (Severity.MODERATE, Severity.SEVERE)
            for a in self.analyses
        )


# ── Google Drive Sync Guard ───────────────────────────────────────────────────


def _compute_sha256(filepath: Path) -> str:
    """Compute SHA256 hash of a file using chunked reads to avoid OOM on large images."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_stable_photos(
    sync_dir: Path,
    settle_seconds: int = 10,
    processed_hashes: set[str] | None = None,
) -> list[InspectionPhoto]:
    """
    Safely ingest photos from a Google Drive sync folder.

    Implements a dual guard:
    1. STALENESS CHECK: Only processes files whose mtime is older than
       `settle_seconds` ago. Google Drive Desktop writes temporary partial
       files during sync — this prevents ingesting corrupt/incomplete images.
    2. SHA256 DEDUPLICATION: Skips any file whose content hash already
       exists in `processed_hashes`. This prevents reprocessing the same
       photo if the pipeline is run multiple times against the same folder.

    Args:
        sync_dir: Path to the Google Drive sync folder containing roof photos.
        settle_seconds: Minimum seconds since last file modification before
                        a file is considered fully synced. Default 10.
        processed_hashes: Optional set of SHA256 hashes from prior runs.
                          Files matching these hashes are skipped.

    Returns:
        List of InspectionPhoto objects for all stable, unique image files.
    """
    if processed_hashes is None:
        processed_hashes = set()

    if not sync_dir.exists():
        logger.warning("sync_dir_not_found", path=str(sync_dir))
        return []

    if not sync_dir.is_dir():
        logger.error("sync_path_not_directory", path=str(sync_dir))
        return []

    now = time.time()
    stable_photos: list[InspectionPhoto] = []
    skipped_settling = 0
    skipped_duplicate = 0
    skipped_extension = 0

    for entry in sorted(sync_dir.iterdir()):
        # Skip directories and hidden files (Drive creates .tmp/.gd* files)
        if entry.is_dir() or entry.name.startswith("."):
            continue

        # Extension filter
        if entry.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
            skipped_extension += 1
            continue

        # Guard 1: Staleness check — file must not have been modified recently
        try:
            mtime = os.path.getmtime(entry)
        except OSError:
            logger.warning("mtime_read_failed", file=entry.name)
            continue

        age_seconds = now - mtime
        if age_seconds < settle_seconds:
            skipped_settling += 1
            logger.debug(
                "file_still_settling",
                file=entry.name,
                age_seconds=round(age_seconds, 1),
                threshold=settle_seconds,
            )
            continue

        # Guard 2: SHA256 deduplication
        file_hash = _compute_sha256(entry)
        if file_hash in processed_hashes:
            skipped_duplicate += 1
            logger.debug("duplicate_skipped", file=entry.name, sha256=file_hash[:12])
            continue

        # File is stable and unique — add to ingestion batch
        processed_hashes.add(file_hash)

        captured_at = datetime.fromtimestamp(mtime)
        stable_photos.append(
            InspectionPhoto(
                filepath=entry,
                captured_at=captured_at,
                sha256=file_hash,
            )
        )

    logger.info(
        "drive_sync_ingestion_complete",
        stable=len(stable_photos),
        skipped_settling=skipped_settling,
        skipped_duplicate=skipped_duplicate,
        skipped_extension=skipped_extension,
        sync_dir=str(sync_dir),
    )

    return stable_photos


# ── Deterministic Condition Index ─────────────────────────────────────────────

class ConditionIndex(BaseModel):
    score: int = Field(ge=0, le=100)
    grade: str
    flags: list[str] = []

def calculate_condition_index(job: InspectionJob, damage_signals: list[dict] = None) -> ConditionIndex:
    """
    Deterministically calculates a 0-100 condition score based on inspection
    analyses and field photo damage signals. AI is strictly excluded from this math.
    """
    if damage_signals is None:
        damage_signals = []
        
    base_score = 100
    flags = []
    
    # 1. Deduct based on structured photo analyses from Google Drive ingestion
    hail_count = 0
    wind_count = 0
    severe_count = 0
    granule_loss_count = 0
    
    for analysis in job.analyses:
        if analysis.damage_detected:
            if analysis.severity == Severity.MINOR:
                base_score -= 2
            elif analysis.severity == Severity.MODERATE:
                base_score -= 5
            elif analysis.severity == Severity.SEVERE:
                base_score -= 10
                severe_count += 1
                
        if analysis.damage_type == DamageType.HAIL or analysis.hail_hits_visible:
            hail_count += 1
        if analysis.damage_type == DamageType.WIND or analysis.crease_marks:
            wind_count += 1
        if analysis.granule_loss or analysis.exposed_fiberglass:
            granule_loss_count += 1
            base_score -= 3
            
    # 2. Deduct based on live Field Photo damage signals
    for sig in damage_signals:
        if sig.get("confidence", 0) > 0.70 and not sig.get("needs_review"):
            dtype = sig.get("damage_type")
            if dtype in ["hail", "wind"]:
                base_score -= 5
            elif dtype == "other":
                base_score -= 2
                
    # Bound the score
    score = max(0, min(100, int(base_score)))
    
    # Calculate Grade
    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 70:
        grade = "C"
    elif score >= 60:
        grade = "D"
    else:
        grade = "F"
        
    # Generate deterministic flags
    if score < 70 or severe_count >= 2:
        flags.append("full_replacement_recommended")
    if hail_count >= 3 and wind_count >= 3:
        flags.append("complex_peril_combination")
    if grade in ["D", "F"]:
        flags.append("high_supplement_potential")
    if granule_loss_count >= 5:
        flags.append("severe_aging_detected")
        
    return ConditionIndex(score=score, grade=grade, flags=flags)
