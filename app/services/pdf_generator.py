"""
PDF document generator using ReportLab.

Renders AI-generated structured data (e.g., itemized material breakdowns)
into clean, branded PDF documents. These PDFs bypass JobNimbus's built-in
templates for full layout control.

Implementation: Phase 5
"""

import tempfile
import asyncio
import structlog
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    ListFlowable,
    ListItem,
)
from reportlab.lib.styles import getSampleStyleSheet

logger = structlog.get_logger("app.services.pdf_generator")


class PDFGenerator:
    """
    ReportLab-based PDF renderer for CRM document generation.

    Phase 5 implementation will provide:
    - generate_material_list(data: dict, output_path: str) -> str: Render material PDF
    - _apply_branding(canvas): Apply Wickham Roofing header/footer
    - _build_table(items: list): Construct formatted data tables
    """

    def __init__(self) -> None:
        self.styles = getSampleStyleSheet()
        logger.info("pdf_generator_initialized")

    async def generate_estimate_pdf(self, data: dict, jnid: str) -> str:
        """
        Generate a PDF estimate from AI-structured data and return the absolute filepath.
        Uses a secure temporary file that the caller should clean up when done.
        """
        log = logger.bind(jnid=jnid)
        log.info("pdf_generation_started")

        # Create a secure temporary file that persists until manually deleted
        temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        filepath = temp_file.name
        temp_file.close()  # Close so ReportLab can write to it

        def build_pdf():
            doc = SimpleDocTemplate(filepath, pagesize=letter)
            story = []

            # Header
            header_style = self.styles["Heading1"]
            story.append(Paragraph("Wickham Roofing Estimate", header_style))
            story.append(Spacer(1, 12))

            # Metadata
            normal_style = self.styles["Normal"]
            story.append(Paragraph(f"<b>Job ID:</b> {jnid}", normal_style))
            story.append(Spacer(1, 12))

            # Materials
            story.append(Paragraph("<b>Materials:</b>", normal_style))
            materials = data.get("materials", [])
            if materials:
                # Create a bulleted list of materials
                bullet_items = [
                    ListItem(Paragraph(str(m), normal_style)) for m in materials
                ]
                story.append(ListFlowable(bullet_items, bulletType="bullet"))
            else:
                story.append(Paragraph("No materials specified.", normal_style))
            story.append(Spacer(1, 12))

            # Total Cost
            total_cost = data.get("total_cost", 0.0)
            story.append(
                Paragraph(f"<b>Total Cost:</b> ${total_cost:,.2f}", normal_style)
            )

            doc.build(story)

        try:
            # Run the synchronous ReportLab generation in a thread
            await asyncio.to_thread(build_pdf)
            log.info("pdf_generation_complete", filepath=filepath)
            return filepath
        except Exception as exc:
            log.error("pdf_generation_failed", error=str(exc))
            raise
