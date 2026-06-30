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
import datetime

from app.core.supplement_models import DiscrepancyReport, MaterialBOM
from app.core.inspection_models import InspectionJob
from pathlib import Path

logger = structlog.get_logger("app.services.pdf_generator")

FIELD_DOCS_DIR = Path("field_docs")


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

    async def generate_material_po(self, job: dict, bom: MaterialBOM, supplier_name: str, delivery_date: str) -> str:
        """
        Generate a Material Purchase Order PDF for the supplier.
        Returns the absolute filepath to the saved PDF.
        """
        log = logger.bind(job_id=job["id"], supplier=supplier_name)
        log.info("material_po_generation_started")

        filepath = str(FIELD_DOCS_DIR / job["id"] / f"PO_{supplier_name.replace(' ', '_')}.pdf")
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        def build_pdf():
            doc = SimpleDocTemplate(filepath, pagesize=letter)
            story = []
            
            # Styles
            header_style = self.styles["Heading1"]
            normal_style = self.styles["Normal"]
            
            # --- 1. Company Header Block ---
            story.append(Paragraph("<b>Wickham Roofing LLC - Purchase Order</b>", header_style))
            story.append(Paragraph("3074 Ellen St., Ochlocknee, GA, 31773 | Phone: (555) 123-4567", normal_style))
            story.append(Spacer(1, 12))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceBefore=0, spaceAfter=12))
            
            # --- 2. Order Details ---
            story.append(Paragraph(f"<b>Supplier:</b> {supplier_name}", normal_style))
            story.append(Paragraph(f"<b>Order Date:</b> {datetime.date.today().isoformat()}", normal_style))
            story.append(Paragraph(f"<b>Requested Delivery Date:</b> {delivery_date}", normal_style))
            story.append(Spacer(1, 12))
            
            story.append(Paragraph("<b>Delivery Information:</b>", self.styles["Heading3"]))
            story.append(Paragraph(f"<b>Homeowner:</b> {job['homeowner_name']}", normal_style))
            story.append(Paragraph(f"<b>Address:</b> {job['address_line1']}, {job['city']}, {job['state']} {job['postal_code']}", normal_style))
            story.append(Paragraph(f"<b>Claim #:</b> {job.get('claim_number', 'N/A')}", normal_style))
            story.append(Spacer(1, 18))
            
            # --- 3. BOM Table ---
            story.append(Paragraph("<b>Material Bill of Quantities:</b>", self.styles["Heading3"]))
            story.append(Spacer(1, 6))
            
            table_data = [["Material Type", "Quantity", "Unit"]]
            table_data.append(["Field Shingles", str(bom.field_shingle_bundles), "Bundles"])
            table_data.append(["Starter Shingles", str(bom.starter_bundles), "Bundles"])
            table_data.append(["Hip & Ridge", str(bom.ridge_cap_bundles), "Bundles"])
            table_data.append(["Ice & Water Shield", str(bom.ice_water_rolls), "Rolls"])
            table_data.append(["Synthetic Underlayment", str(bom.underlayment_rolls), "Rolls"])
            table_data.append(["Drip Edge (10ft)", str(bom.drip_edge_pieces), "Pieces"])
            
            t = Table(table_data, colWidths=[200, 100, 100])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.grey),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0,0), (-1,0), 8),
                ('BACKGROUND', (0,1), (-1,-1), colors.white),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
            ]))
            story.append(t)
            
            doc.build(story)

        try:
            await asyncio.to_thread(build_pdf)
            log.info("material_po_generation_complete", filepath=filepath)
            return filepath
        except Exception as exc:
            log.error("material_po_generation_failed", error=str(exc))
            raise

    async def generate_notice_of_cancellation(self, job: dict) -> str:
        """
        Generate Georgia statutory Notice of Cancellation.
        """
        temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        filepath = temp_file.name
        temp_file.close()

        def build_pdf():
            doc = SimpleDocTemplate(filepath, pagesize=letter)
            story = []
            
            header_style = self.styles["Heading1"]
            normal_style = self.styles["Normal"]
            
            story.append(Paragraph("<b>NOTICE OF CANCELLATION</b>", header_style))
            story.append(Paragraph(f"Date of Transaction: {datetime.date.today().isoformat()}", normal_style))
            story.append(Spacer(1, 12))
            
            statutory_text = (
                "You may CANCEL this transaction, without any penalty or obligation, within FIVE (5) "
                "BUSINESS DAYS from the above date.<br/><br/>"
                "If you cancel, any property traded in, any payments made by you under the contract or sale, "
                "and any negotiable instrument executed by you will be returned within TEN (10) BUSINESS DAYS "
                "following receipt by the seller of your cancellation notice, and any security interest arising "
                "out of the transaction will be canceled.<br/><br/>"
                "To cancel this transaction, mail or deliver a signed and dated copy of this cancellation notice "
                "or any other written notice, or send a telegram, to Wickham Roofing LLC at 3074 Ellen St., "
                "Ochlocknee, GA, 31773 NOT LATER THAN MIDNIGHT OF THE FIFTH BUSINESS DAY FOLLOWING THE TRANSACTION DATE."
            )
            story.append(Paragraph(statutory_text, normal_style))
            story.append(Spacer(1, 40))
            
            story.append(Paragraph("I HEREBY CANCEL THIS TRANSACTION.", normal_style))
            story.append(Spacer(1, 40))
            story.append(HRFlowable(width="50%", thickness=1, color=colors.black, hAlign='LEFT'))
            story.append(Paragraph("Homeowner Signature", normal_style))
            story.append(Spacer(1, 10))
            story.append(HRFlowable(width="50%", thickness=1, color=colors.black, hAlign='LEFT'))
            story.append(Paragraph("Date", normal_style))
            
            doc.build(story)

        await asyncio.to_thread(build_pdf)
        return filepath

    async def generate_certificate_of_completion(self, job: dict, completion_date: str) -> str:
        """
        Generate Certificate of Completion.
        """
        temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        filepath = temp_file.name
        temp_file.close()

        def build_pdf():
            doc = SimpleDocTemplate(filepath, pagesize=letter)
            story = []
            
            header_style = self.styles["Heading1"]
            normal_style = self.styles["Normal"]
            
            story.append(Paragraph("<b>CERTIFICATE OF COMPLETION</b>", header_style))
            story.append(Spacer(1, 12))
            
            text = (
                f"This document certifies that Wickham Roofing LLC has satisfactorily completed "
                f"all roofing services per the agreed scope of work at the property located at:<br/><br/>"
                f"<b>{job['address_line1']}, {job['city']}, {job['state']} {job['postal_code']}</b><br/><br/>"
                f"for the homeowner, <b>{job['homeowner_name']}</b>, on <b>{completion_date}</b>.<br/><br/>"
                f"All work has been performed in compliance with applicable local and state building codes."
            )
            story.append(Paragraph(text, normal_style))
            story.append(Spacer(1, 40))
            
            story.append(HRFlowable(width="50%", thickness=1, color=colors.black, hAlign='LEFT'))
            story.append(Paragraph("Homeowner Signature & Date", normal_style))
            story.append(Spacer(1, 30))
            
            story.append(HRFlowable(width="50%", thickness=1, color=colors.black, hAlign='LEFT'))
            story.append(Paragraph("Wickham Roofing LLC Representative & Date", normal_style))
            
            doc.build(story)

        await asyncio.to_thread(build_pdf)
        return filepath
