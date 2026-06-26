"""
Unit tests for the EagleView PDF extractor.

Tests cover:
1. Successful extraction from a mock Report Summary page
2. Handling of missing Report Summary page
3. File not found error
4. Real PDF extraction (if the sample file exists)
"""

import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from app.services.pdf_extractor import (
    extract_eagleview_data,
    _parse_length,
    _parse_total_area,
    _parse_predominant_pitch,
    _parse_total_facets,
    _extract_from_page,
)


# ---------------------------------------------------------------------------
# Test: Text parsing helpers
# ---------------------------------------------------------------------------
class TestTextParsers:
    """Tests for the regex-based text parsing functions."""

    SAMPLE_TEXT = """
    Ridges = 120 ft (12 Ridges)
    Hips = 315 ft (14 Hips).
    Valleys = 288 ft (17 Valleys)
    Rakes* = 114 ft (12 Rakes)
    Eaves/Starter** = 276 ft (26 Eaves)
    Drip Edge (Eaves + Rakes) = 390 ft (38 Lengths)
    Flashing = 3 ft (2 Lengths)
    Step flashing = 16 ft (2 Lengths)
    Total Area = 6,788 sq ft
    Total Roof Facets = 26 Predominant Pitch = 10/12
    """

    def test_parse_ridges(self):
        assert _parse_length(self.SAMPLE_TEXT, "Ridges") == 120.0

    def test_parse_hips(self):
        assert _parse_length(self.SAMPLE_TEXT, "Hips") == 315.0

    def test_parse_valleys(self):
        assert _parse_length(self.SAMPLE_TEXT, "Valleys") == 288.0

    def test_parse_rakes(self):
        assert _parse_length(self.SAMPLE_TEXT, "Rakes") == 114.0

    def test_parse_eaves(self):
        assert _parse_length(self.SAMPLE_TEXT, "Eaves") == 276.0

    def test_parse_drip_edge(self):
        assert _parse_length(self.SAMPLE_TEXT, "Drip Edge") == 390.0

    def test_parse_flashing(self):
        assert _parse_length(self.SAMPLE_TEXT, "Flashing") == 3.0

    def test_parse_step_flashing(self):
        assert _parse_length(self.SAMPLE_TEXT, "Step Flashing") == 16.0

    def test_parse_missing_label(self):
        assert _parse_length(self.SAMPLE_TEXT, "Skylights") == 0.0

    def test_parse_total_area(self):
        assert _parse_total_area(self.SAMPLE_TEXT) == 6788.0

    def test_parse_predominant_pitch(self):
        assert _parse_predominant_pitch(self.SAMPLE_TEXT) == "10/12"

    def test_parse_total_facets(self):
        assert _parse_total_facets(self.SAMPLE_TEXT) == 26


# ---------------------------------------------------------------------------
# Test: Mock page extraction
# ---------------------------------------------------------------------------
class TestExtractFromPage:
    """Tests for page-level extraction using mock pdfplumber page."""

    def test_extract_with_table_and_text(self):
        """Should extract area from table and lengths from text."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "Ridges = 50 ft\n"
            "Hips = 100 ft\n"
            "Valleys = 75 ft\n"
            "Rakes* = 40 ft\n"
            "Eaves/Starter** = 80 ft\n"
            "Drip Edge (Eaves + Rakes) = 120 ft\n"
            "Flashing = 5 ft\n"
            "Step flashing = 8 ft\n"
            "Total Area = 3,000 sq ft\n"
            "Total Roof Facets = 12 Predominant Pitch = 8/12\n"
        )
        mock_page.extract_tables.return_value = [
            [
                ["Areas per Pitch", None],
                ["Roof Pitches", "8/12"],
                ["Area (sq ft)", "3000.0"],
            ]
        ]

        result = _extract_from_page(mock_page)

        assert result.total_area_sf == 3000.0
        assert result.ridge_lf == 50.0
        assert result.valley_lf == 75.0
        assert result.predominant_pitch == "8/12"


# ---------------------------------------------------------------------------
# Test: Async extraction function
# ---------------------------------------------------------------------------
class TestExtractEagleviewData:
    """Tests for the main async extraction entry point."""

    def test_file_not_found_raises(self):
        """Should raise FileNotFoundError for missing PDF."""
        with pytest.raises(FileNotFoundError):
            asyncio.run(extract_eagleview_data("/nonexistent/path.pdf"))

    def test_missing_report_summary_raises(self):
        """Should raise ValueError if Report Summary page is not found."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Some other page content"

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("app.services.pdf_extractor.Path.exists", return_value=True):
            with patch("pdfplumber.open", return_value=mock_pdf):
                with pytest.raises(ValueError, match="REPORT SUMMARY"):
                    asyncio.run(extract_eagleview_data("fake.pdf"))


# ---------------------------------------------------------------------------
# Test: Real PDF extraction (integration test)
# ---------------------------------------------------------------------------
class TestRealPDFExtraction:
    """Integration test using the actual sample EagleView PDF."""

    SAMPLE_PDF = Path("EagleView-Sample-Premium_Roof_Report.pdf")

    @pytest.mark.skipif(
        not Path("EagleView-Sample-Premium_Roof_Report.pdf").exists(),
        reason="Sample EagleView PDF not available",
    )
    def test_extract_from_real_eagleview_pdf(self):
        """Validate extraction against known values from the sample report."""
        result = asyncio.run(extract_eagleview_data(str(self.SAMPLE_PDF)))

        # These values are verified from the actual PDF
        assert result.total_area_sf == 6788.0
        assert result.ridge_lf == 120.0
        assert result.hip_lf == 315.0
        assert result.valley_lf == 288.0
        assert result.rake_lf == 114.0
        assert result.eaves_lf == 276.0
        assert result.drip_edge_lf == 390.0
        assert result.flashing_lf == 3.0
        assert result.step_flashing_lf == 16.0
        assert result.total_facets == 26
        assert result.predominant_pitch == "10/12"
