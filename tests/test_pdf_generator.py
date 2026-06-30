"""
Unit tests for the PDF Generator.
"""

import asyncio
from pathlib import Path

from app.services.pdf_generator import PDFGenerator


def test_generate_estimate_pdf_creates_file():
    """Test that the PDF generator creates a valid file on disk."""
    generator = PDFGenerator()

    test_data = {
        "materials": ["Asphalt Shingles", "Nails", "Underlayment"],
        "total_cost": 12500.50,
    }

    filepath = asyncio.run(generator.generate_estimate_pdf(test_data, "job123"))

    path_obj = Path(filepath)

    try:
        # Verify the file was created and is not empty
        assert path_obj.exists()
        assert path_obj.is_file()
        assert path_obj.stat().st_size > 0
    finally:
        # Clean up the temporary file
        if path_obj.exists():
            path_obj.unlink()


def test_generate_estimate_pdf_handles_missing_data():
    """Test PDF generation works even if data is missing."""
    generator = PDFGenerator()

    test_data = {}  # Empty data

    filepath = asyncio.run(generator.generate_estimate_pdf(test_data, "job456"))
    path_obj = Path(filepath)

    try:
        assert path_obj.exists()
        assert path_obj.stat().st_size > 0
    finally:
        if path_obj.exists():
            path_obj.unlink()

from app.core.inspection_models import InspectionJob, InspectionPhoto, PhotoAnalysis, DamageType, Severity

def test_generate_evidence_grid_creates_file(tmp_path):
    """Test that the Evidence Grid creates a valid multi-page PDF."""
    generator = PDFGenerator()
    
    # Create a dummy image file for ReportLab to render
    from PIL import Image as PILImage
    img_path = tmp_path / "test_photo.jpg"
    img = PILImage.new("RGB", (800, 600), color="red")
    img.save(img_path, format="JPEG")
    
    sig_path = tmp_path / "sig.png"
    sig_img = PILImage.new("RGBA", (200, 50), color="blue")
    sig_img.save(sig_path, format="PNG")
    
    from datetime import datetime
    
    # Construct a valid InspectionJob
    job = InspectionJob(
        job_id="TEST-GRID-001",
        property_address="123 Test St",
        inspection_date=datetime.now(),
        photos=[
            InspectionPhoto(filepath=img_path, sha256="fake_hash", captured_at="2026-06-30T10:00:00Z")
        ],
        analyses=[
            PhotoAnalysis(
                filename=img_path.name,
                damage_detected=True,
                damage_type=DamageType.HAIL,
                severity=Severity.MODERATE,
                hail_hits_visible=True,
                crease_marks=False,
                granule_loss=True,
                exposed_fiberglass=False,
                confidence=0.98,
                forensic_narrative="Hail impacts visible across the soft metals and shingle mat."
            )
        ]
    )

    filepath = asyncio.run(generator.generate_evidence_grid(job, signature_path=str(sig_path)))
    path_obj = Path(filepath)

    try:
        assert path_obj.exists()
        assert path_obj.stat().st_size > 0
    finally:
        if path_obj.exists():
            path_obj.unlink()
