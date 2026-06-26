"""
Deterministic PDF extractor for EagleView Premium Roof Reports.

Uses pdfplumber (not LLM) to extract structured measurement data
from EagleView's highly formatted report tables. This is the first
stage of the supplement pipeline.

Design decisions:
- Targets the Report Summary page (typically the last page)
- Extracts table data for area/pitch, text-parses for line lengths
- Falls back to full-text regex if table extraction fails (scanned PDFs)
- Logs a LOW_CONFIDENCE warning on fallback for human review
"""

import re
import asyncio
from pathlib import Path

import pdfplumber
import pdfplumber.page
import structlog

from app.core.supplement_models import EagleViewData

logger = structlog.get_logger("app.services.pdf_extractor")


def _parse_length(text: str, label: str) -> float:
    """
    Extract a numeric length value from EagleView report text.

    Matches patterns like:
      - "Valleys = 288 ft"
      - "Ridges = 120 ft (12 Ridges)"
      - "Drip Edge (Eaves + Rakes) = 390 ft"

    Returns 0.0 if the label is not found.
    """
    # Handle special label for Drip Edge
    if label.lower() == "drip edge":
        pattern = r"Drip\s+Edge\s*\([^)]+\)\s*=\s*([\d,]+)\s*ft"
    elif label.lower() == "step flashing":
        pattern = rf"Step\s+flashing\s*=\s*([\d,]+)\s*ft"
    elif label.lower() == "eaves":
        pattern = r"Eaves/Starter\*?\*?\s*=\s*([\d,]+)\s*ft"
    else:
        pattern = rf"{re.escape(label)}\s*\*?\*?\s*=\s*([\d,]+)\s*ft"

    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(",", ""))
    return 0.0


def _parse_total_area(text: str) -> float:
    """Extract Total Area from 'Total Area = X,XXX sq ft' pattern."""
    match = re.search(r"Total\s+Area\s*=\s*([\d,]+(?:\.\d+)?)\s*sq\s*ft", text, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(",", ""))
    return 0.0


def _parse_predominant_pitch(text: str) -> str:
    """Extract Predominant Pitch from 'Predominant Pitch = X/12' pattern."""
    match = re.search(r"Predominant\s+Pitch\s*=\s*(\d+/\d+)", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return "unknown"


def _parse_total_facets(text: str) -> int:
    """Extract Total Roof Facets from 'Total Roof Facets = XX' pattern."""
    match = re.search(r"Total\s+Roof\s+Facets\s*=\s*(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 0


def _find_report_summary_page(pdf) -> pdfplumber.page.Page | None:
    """
    Locate the Report Summary page by scanning for the header text.
    Typically the last page, but we search to be safe.
    """
    for page in reversed(pdf.pages):
        text = page.extract_text() or ""
        if "REPORT SUMMARY" in text:
            return page
    return None


def _extract_from_page(page: pdfplumber.page.Page, waste_factor: float = 0.15) -> EagleViewData:
    """
    Extract all EagleView measurement data from the Report Summary page.

    Strategy:
    1. Try table extraction for structured area/pitch data
    2. Always use text parsing for line lengths (they're in prose, not tables)
    """
    text = page.extract_text() or ""
    tables = page.extract_tables()

    # --- Extract Total Area ---
    # First try from the Areas per Pitch table
    total_area = 0.0
    for table in tables:
        for row in table:
            if row and row[0] and "area" in str(row[0]).lower() and "sq ft" in str(row[0]).lower():
                try:
                    total_area = float(str(row[1]).replace(",", ""))
                except (ValueError, TypeError, IndexError):
                    pass

    # Fallback to text parsing if table didn't yield area
    if total_area == 0.0:
        total_area = _parse_total_area(text)

    # If still zero, try the waste calculation table (0% waste row)
    if total_area == 0.0:
        for table in tables:
            for row in table:
                if row and row[0] and "area" in str(row[0]).lower() and len(row) > 1:
                    try:
                        total_area = float(str(row[1]).replace(",", ""))
                    except (ValueError, TypeError):
                        pass

    # --- Extract line lengths from text ---
    ridge_lf = _parse_length(text, "Ridges")
    hip_lf = _parse_length(text, "Hips")
    valley_lf = _parse_length(text, "Valleys")
    rake_lf = _parse_length(text, "Rakes")
    eaves_lf = _parse_length(text, "Eaves")
    drip_edge_lf = _parse_length(text, "Drip Edge")
    flashing_lf = _parse_length(text, "Flashing")
    step_flashing_lf = _parse_length(text, "Step Flashing")

    # --- Extract pitch and facets ---
    predominant_pitch = _parse_predominant_pitch(text)
    total_facets = _parse_total_facets(text)

    return EagleViewData(
        total_area_sf=total_area,
        rake_lf=rake_lf,
        valley_lf=valley_lf,
        ridge_lf=ridge_lf,
        hip_lf=hip_lf,
        eaves_lf=eaves_lf,
        drip_edge_lf=drip_edge_lf,
        flashing_lf=flashing_lf,
        step_flashing_lf=step_flashing_lf,
        total_facets=total_facets,
        predominant_pitch=predominant_pitch,
        waste_factor=waste_factor,
    )


async def extract_eagleview_data(
    pdf_path: str | Path,
    waste_factor: float = 0.15,
) -> EagleViewData:
    """
    Extract structured measurement data from an EagleView Premium Roof Report PDF.

    Args:
        pdf_path: Path to the EagleView PDF file.
        waste_factor: Waste factor to apply (default 15%).

    Returns:
        EagleViewData with all measurements and computed normalized_squares.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        ValueError: If the Report Summary page cannot be found.
    """
    pdf_path = Path(pdf_path)
    log = logger.bind(pdf_path=str(pdf_path))

    if not pdf_path.exists():
        log.error("eagleview_pdf_not_found")
        raise FileNotFoundError(f"EagleView PDF not found: {pdf_path}")

    log.info("eagleview_extraction_started")

    def _extract():
        with pdfplumber.open(str(pdf_path)) as pdf:
            summary_page = _find_report_summary_page(pdf)
            if summary_page is None:
                raise ValueError(
                    "Could not locate 'REPORT SUMMARY' page in EagleView PDF. "
                    "The document may be incomplete or in an unexpected format."
                )

            data = _extract_from_page(summary_page, waste_factor=waste_factor)

            # Validate we got meaningful data
            if data.total_area_sf == 0.0:
                log.warning(
                    "eagleview_low_confidence_extraction",
                    reason="Total area is 0.0 — possible scanned/image-only PDF",
                )

            return data

    # Run pdfplumber in a thread to avoid blocking the event loop
    result = await asyncio.to_thread(_extract)

    log.info(
        "eagleview_extraction_complete",
        total_area_sf=result.total_area_sf,
        normalized_squares=result.normalized_squares,
        predominant_pitch=result.predominant_pitch,
    )

    return result
