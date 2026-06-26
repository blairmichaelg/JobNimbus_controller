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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle

from app.core.supplement_models import DiscrepancyReport

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
            
            # Styles
            header_style = self.styles["Heading1"]
            normal_style = self.styles["Normal"]
            
            # Custom Legal Style
            legal_style = ParagraphStyle(
                name="LegalDisclaimer",
                parent=self.styles["Normal"],
                fontSize=8,
                leading=10,
                textColor=colors.dimgrey,
            )
            
            # --- 1. Company Header Block ---
            story.append(Paragraph("<b>Wickham Roofing LLC</b>", header_style))
            story.append(Paragraph("3074 Ellen St., Ochlocknee, GA, 31773", normal_style))
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceBefore=0, spaceAfter=12))
            
            # --- 2. Metadata ---
            story.append(Paragraph("<b>Roofing Estimate</b>", self.styles["Heading2"]))
            story.append(Paragraph(f"<b>Job ID:</b> {jnid}", normal_style))
            story.append(Spacer(1, 12))
            
            # --- 3. Materials ---
            story.append(Paragraph("<b>Scope of Work / Materials:</b>", normal_style))
            materials = data.get("materials", [])
            if materials:
                bullet_items = [ListItem(Paragraph(str(m), normal_style)) for m in materials]
                story.append(ListFlowable(bullet_items, bulletType='bullet'))
            else:
                story.append(Paragraph("No materials specified.", normal_style))
            story.append(Spacer(1, 12))
            
            # --- 4. Total Cost ---
            total_cost = data.get("total_cost", 0.0)
            story.append(Paragraph(f"<b>Total Cost:</b> ${total_cost:,.2f}", normal_style))
            story.append(Spacer(1, 40))
            
            # --- 5. Legal Terms & Disclaimers Boilerplate ---
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceBefore=0, spaceAfter=12))
            legal_text = (
                "<b>Scope of Work:</b> This estimate covers explicitly listed materials and applications. "
                "Any hidden structural rot, decking damage, or code upgrades discovered during tear-off "
                "will be handled via a supplemental change order.<br/><br/>"
                "<b>Payment Terms:</b> All balances are due upon job completion. Unpaid invoices past 30 days "
                "are subject to standard financing interest rates as specified by corporate policy."
            )
            story.append(Paragraph(legal_text, legal_style))
            
            doc.build(story)

        try:
            # Run the synchronous ReportLab generation in a thread
            await asyncio.to_thread(build_pdf)
            log.info("pdf_generation_complete", filepath=filepath)
            return filepath
        except Exception as exc:
            log.error("pdf_generation_failed", error=str(exc))
            raise

    async def generate_supplement_pdf(self, report: DiscrepancyReport, narrative: str, jnid: str) -> str:
        """
        Generate a Supplement Request PDF including the discrepancy summary and AI narrative.
        Returns the absolute filepath to the temporary PDF.
        """
        log = logger.bind(jnid=jnid)
        log.info("supplement_pdf_generation_started")

        temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        filepath = temp_file.name
        temp_file.close()

        def build_pdf():
            doc = SimpleDocTemplate(filepath, pagesize=letter)
            story = []
            
            # Styles
            header_style = self.styles["Heading1"]
            normal_style = self.styles["Normal"]
            narrative_style = ParagraphStyle(
                name="Narrative",
                parent=normal_style,
                spaceBefore=6,
                spaceAfter=6,
            )
            legal_style = ParagraphStyle(
                name="LegalDisclaimer",
                parent=normal_style,
                fontSize=8,
                leading=10,
                textColor=colors.dimgrey,
            )
            
            # --- 1. Company Header Block ---
            story.append(Paragraph("<b>Wickham Roofing LLC</b>", header_style))
            story.append(Paragraph("3074 Ellen St., Ochlocknee, GA, 31773", normal_style))
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceBefore=0, spaceAfter=12))
            
            # --- 2. Title ---
            story.append(Paragraph("<b>SUPPLEMENT REQUEST</b>", self.styles["Heading2"]))
            story.append(Paragraph(f"<b>Job ID:</b> {jnid}", normal_style))
            story.append(Spacer(1, 12))
            
            # --- 3. Discrepancy Table ---
            story.append(Paragraph("<b>Summary of Mathematical Variances:</b>", normal_style))
            story.append(Spacer(1, 6))
            
            table_data = [["Category", "EV Value", "SoL Value", "Variance"]]
            for d in report.discrepancies:
                table_data.append([
                    d.category,
                    str(d.ev_value) if d.ev_value is not None else "N/A",
                    str(d.sol_value) if d.sol_value is not None else "N/A",
                    str(d.variance) if d.variance is not None else "N/A",
                ])
                
            if len(table_data) > 1:
                t = Table(table_data, colWidths=[150, 100, 100, 100])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.grey),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                    ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('BOTTOMPADDING', (0,0), (-1,0), 12),
                    ('BACKGROUND', (0,1), (-1,-1), colors.beige),
                    ('GRID', (0,0), (-1,-1), 1, colors.black),
                ]))
                story.append(t)
            else:
                story.append(Paragraph("No discrepancies found.", normal_style))
            story.append(Spacer(1, 18))
            
            # --- 4. Narrative ---
            story.append(Paragraph("<b>Contractor Notes & Code Requirements:</b>", normal_style))
            story.append(Spacer(1, 6))
            # Split narrative by newlines into separate paragraphs
            for p in narrative.split("\n"):
                if p.strip():
                    story.append(Paragraph(p.strip(), narrative_style))
            story.append(Spacer(1, 24))
            
            # --- 5. Legal Terms & Disclaimers Boilerplate ---
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceBefore=0, spaceAfter=12))
            legal_text = (
                "<b>Scope of Work:</b> This estimate covers explicitly listed materials and applications. "
                "Any hidden structural rot, decking damage, or code upgrades discovered during tear-off "
                "will be handled via a supplemental change order.<br/><br/>"
                "<b>Payment Terms:</b> All balances are due upon job completion. Unpaid invoices past 30 days "
                "are subject to standard financing interest rates as specified by corporate policy."
            )
            story.append(Paragraph(legal_text, legal_style))
            
            doc.build(story)

        try:
            await asyncio.to_thread(build_pdf)
            log.info("supplement_pdf_generation_complete", filepath=filepath)
            return filepath
        except Exception as exc:
            log.error("supplement_pdf_generation_failed", error=str(exc))
            raise
