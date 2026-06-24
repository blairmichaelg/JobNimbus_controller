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
