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
from reportlab.platypus import Table, TableStyle, Image, PageBreak

from app.core.supplement_models import DiscrepancyReport
from app.core.inspection_models import InspectionJob

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

    async def generate_evidence_grid(self, job: InspectionJob, signature_path: str | None = None) -> str:
        """
        Generate a multi-page Evidence Grid appendix for the Inspection Engine.
        Layout: Strict 2-column format. Left: Photo. Right: Boolean flags + narrative.
        Max 2 photos per page. Appends a signature at the end if provided.
        """
        log = logger.bind(job_id=job.job_id)
        log.info("evidence_grid_generation_started")

        temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        filepath = temp_file.name
        temp_file.close()

        def build_pdf():
            doc = SimpleDocTemplate(filepath, pagesize=letter)
            story = []
            
            # Styles
            header_style = self.styles["Heading1"]
            normal_style = self.styles["Normal"]
            
            # Sub-table style for the dense data box
            data_box_style = TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.darkgrey),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0,0), (-1,0), 6),
                ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
                ('GRID', (0,0), (-1,-1), 1, colors.lightgrey),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ])

            # --- 1. Header ---
            story.append(Paragraph("<b>Wickham Roofing LLC - Inspection Evidence Grid</b>", header_style))
            story.append(Paragraph(f"<b>Job ID:</b> {job.job_id} | <b>Address:</b> {job.property_address}", normal_style))
            story.append(Spacer(1, 12))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=12))

            # --- 2. Photos & Analysis ---
            if not job.analyses:
                story.append(Paragraph("No photos analyzed.", normal_style))
            
            photos_on_page = 0
            for idx, analysis in enumerate(job.analyses):
                if photos_on_page >= 2:
                    story.append(PageBreak())
                    photos_on_page = 0
                
                # Match analysis to original photo by filename
                photo_record = next((p for p in job.photos if p.filepath.name == analysis.filename), None)
                if not photo_record:
                    continue
                
                try:
                    # Render image with proportional constraint (max width 300 to fit half page)
                    img = Image(str(photo_record.filepath), width=300, height=200, kind='proportional')
                    
                    # Create data box table
                    data_rows = [
                        ["Forensic Metric", "Result"],
                        ["Damage Detected", "Yes" if analysis.damage_detected else "No"],
                        ["Classification", analysis.damage_type.value.capitalize()],
                        ["Severity", analysis.severity.value.capitalize()],
                        ["Hail Hits Visible", "Yes" if analysis.hail_hits_visible else "No"],
                        ["Crease Marks", "Yes" if analysis.crease_marks else "No"],
                        ["Granule Loss", "Yes" if analysis.granule_loss else "No"],
                        ["Exposed Fiberglass", "Yes" if analysis.exposed_fiberglass else "No"],
                        ["Confidence", f"{analysis.confidence * 100:.1f}%"],
                    ]
                    
                    data_table = Table(data_rows, colWidths=[120, 80])
                    data_table.setStyle(data_box_style)
                    
                    # Wrap the narrative in a Paragraph so it wraps inside the cell
                    narrative_para = Paragraph(analysis.forensic_narrative, normal_style)
                    narrative_table = Table([[narrative_para]], colWidths=[200])
                    narrative_table.setStyle(TableStyle([
                        ('BACKGROUND', (0,0), (-1,-1), colors.beige),
                        ('BOX', (0,0), (-1,-1), 1, colors.lightgrey),
                        ('TOPPADDING', (0,0), (-1,-1), 6),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                    ]))

                    # Create a vertical container for the data box + narrative
                    info_column = [data_table, Spacer(1, 6), narrative_table]
                    
                    # Main grid row: [Image, InfoColumn]
                    grid_table = Table([[img, info_column]], colWidths=[310, 210])
                    grid_table.setStyle(TableStyle([
                        ('VALIGN', (0,0), (-1,-1), 'TOP'),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 20),
                    ]))
                    
                    story.append(grid_table)
                    photos_on_page += 1
                except Exception as e:
                    log.warning("photo_render_skipped", filename=analysis.filename, error=str(e))
                    continue

            # --- 3. Signature ---
            if signature_path:
                story.append(Spacer(1, 20))
                story.append(Paragraph("<b>Homeowner Authorization</b>", self.styles["Heading2"]))
                story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=12))
                try:
                    # Signatures from Canvas are usually wide.
                    sig_img = Image(str(signature_path), width=300, height=100, kind='proportional')
                    story.append(sig_img)
                    story.append(Paragraph(f"Digitally signed on {job.inspection_date.strftime('%Y-%m-%d')}", normal_style))
                except Exception as e:
                    log.error("signature_render_failed", error=str(e))

            doc.build(story)

        try:
            await asyncio.to_thread(build_pdf)
            log.info("evidence_grid_generation_complete", filepath=filepath)
            return filepath
        except Exception as exc:
            log.error("evidence_grid_generation_failed", error=str(exc))
            raise
