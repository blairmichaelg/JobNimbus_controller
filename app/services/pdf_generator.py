"""
PDF document generator using ReportLab.

Renders AI-generated structured data (e.g., itemized material breakdowns)
into clean, branded PDF documents. These PDFs bypass JobNimbus's built-in
templates for full layout control.

Implementation: Phase 5
"""

import asyncio
import structlog
from reportlab.lib.pagesizes import letter
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, KeepTogether
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Image, PageBreak
import datetime
import html

from app.core.supplement_models import DiscrepancyReport, MaterialBOM
from app.core.inspection_models import InspectionJob
from pathlib import Path

logger = structlog.get_logger("app.services.pdf_generator")

FIELD_DOCS_DIR = Path("data/field_docs")


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
        self._build_custom_styles()
        logger.info("pdf_generator_initialized")

    def _build_custom_styles(self) -> None:
        base_normal = self.styles["Normal"]
        self.custom_styles = {
            "Title": ParagraphStyle(
                "Title", parent=self.styles["Heading1"], fontSize=16, fontName="Helvetica-Bold", alignment=1
            ),
            "SectionHeading": ParagraphStyle(
                "SectionHeading", parent=self.styles["Heading2"], fontSize=11, fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=6
            ),
            "BodyText": ParagraphStyle(
                "BodyText", parent=base_normal, fontSize=10, alignment=4 # 4=TA_JUSTIFY
            ),
            "StatWarning": ParagraphStyle(
                "StatWarning", parent=base_normal, fontSize=10, fontName="Helvetica-Bold", textColor=colors.darkred
            ),
            "FinePrint": ParagraphStyle(
                "FinePrint", parent=base_normal, fontSize=8, textColor=colors.dimgrey, alignment=4
            ),
            "DocControl": ParagraphStyle(
                "DocControl", parent=base_normal, fontSize=10, fontName="Helvetica-Oblique", textColor=colors.darkgrey, alignment=2 # 2=TA_RIGHT
            ),
            "Normal": base_normal,
        }

    def _universal_letterhead(self, canvas, doc) -> None:
        """Universal callback for page headers and footers."""
        canvas.saveState()

        # Header
        canvas.setFont("Helvetica-Bold", 14)
        canvas.drawString(50, 750, "WICKHAM ROOFING, LLC")
        canvas.setFont("Helvetica", 10)
        canvas.drawString(50, 735, "123 Roofing Lane, Thomasville, GA 31792")
        canvas.drawString(50, 720, "Phone: (555) 123-4567 | Email: info@wickhamroofing.com")

        # Line under header
        canvas.setStrokeColor(colors.black)
        canvas.setLineWidth(1)
        canvas.line(50, 710, 560, 710)

        # Footer
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.darkgrey)
        job_id = getattr(doc, 'job_id', 'N/A')
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        canvas.drawString(50, 30, f"DocID: {job_id} | Generated: {timestamp}")
        page_num = canvas.getPageNumber()
        canvas.drawRightString(560, 30, f"Page {page_num}")

        canvas.restoreState()

    def _build_signature_block(self, title1: str = "Homeowner Signature", title2: str = "Contractor Signature", include_witness: bool = False):
        """Returns a KeepTogether flowable for clean signature blocks."""
        story: list = []
        story.append(Spacer(1, 30))

        # Two columns: Signature and Date
        data = [
            ["", ""],
            [title1, "Date"],
            ["(Printed Name)", "(MM/DD/YYYY)"],
            ["", ""],
            [title2, "Date"],
            ["(Printed Name)", "(MM/DD/YYYY)"]
        ]

        if include_witness:
            data.extend([
                ["", ""],
                ["Witness / Notary Signature", "Date"],
                ["(Printed Name)", "(MM/DD/YYYY)"]
            ])

        t = Table(data, colWidths=[250, 100])
        style = [
            ('LINEABOVE', (0,1), (0,1), 1, colors.black),
            ('LINEABOVE', (1,1), (1,1), 1, colors.black),
            ('LINEABOVE', (0,4), (0,4), 1, colors.black),
            ('LINEABOVE', (1,4), (1,4), 1, colors.black),
            ('PADDING', (0,0), (-1,-1), 2),
            ('FONTSIZE', (0,2), (1,2), 8),
            ('TEXTCOLOR', (0,2), (1,2), colors.dimgrey),
            ('FONTSIZE', (0,5), (1,5), 8),
            ('TEXTCOLOR', (0,5), (1,5), colors.dimgrey),
            ('BOTTOMPADDING', (0,2), (-1,2), 20),
        ]

        if include_witness:
            style.extend([
                ('LINEABOVE', (0,7), (0,7), 1, colors.black),
                ('LINEABOVE', (1,7), (1,7), 1, colors.black),
                ('FONTSIZE', (0,8), (1,8), 8),
                ('TEXTCOLOR', (0,8), (1,8), colors.dimgrey),
            ])

        t.setStyle(TableStyle(style)) # type: ignore[arg-type]
        story.append(t)

        return KeepTogether(story)

    def _get_doc_template(self, filepath: str, top_margin: int = 144, job_id: str = "N/A") -> BaseDocTemplate:
        """Returns a BaseDocTemplate configured with a Frame that prevents overlapping with the header."""
        doc = BaseDocTemplate(filepath, pagesize=letter, leftMargin=50, rightMargin=50, topMargin=top_margin, bottomMargin=50)
        doc.job_id = job_id # type: ignore[attr-defined]
        # letter height is 792. Leave space at the top.
        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='normal')
        template = PageTemplate(id='standard', frames=frame, onPage=self._universal_letterhead)
        doc.addPageTemplates([template])
        return doc

    def _build_metadata_table(self, job: dict) -> Table:
        """Constructs a structured metadata table for the top of documents."""
        address = f"{job.get('address_line1', '')}, {job.get('city', '')}, {job.get('state', '')} {job.get('postal_code', '')}"
        data = [
            ["Job ID:", job.get("id", "N/A")],
            ["Homeowner:", job.get("homeowner_name", "N/A")],
            ["Service Address:", address],
            ["Claim #:", job.get("claim_number", "N/A")],
        ]
        t = Table(data, colWidths=[120, 380])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('PADDING', (0,0), (-1,-1), 6),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        return t

    def _box_warning(self, title: str, text: str, border_color) -> Table:
        """Wraps a critical legal warning inside a styled Table box."""
        t_data = [
            [Paragraph(title, self.custom_styles["SectionHeading"])],
            [Paragraph(text, self.custom_styles["StatWarning"])]
        ]
        t = Table(t_data, colWidths=[500])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.whitesmoke),
            ('BOX', (0,0), (-1,-1), 1.5, border_color),
            ('PADDING', (0,0), (-1,-1), 10),
            ('BOTTOMPADDING', (0,0), (0,0), 0), # Reduce space between title and text
        ]))
        return t

    async def generate_estimate_pdf(self, data: dict, job_id: str) -> str:
        """
        Generate a PDF estimate from AI-structured data and return the absolute filepath.
        Uses a secure temporary file that the caller should clean up when done.
        """
        log = logger.bind(job_id=job_id)
        log.info("pdf_generation_started")

        # Create a secure temporary file that persists until manually deleted
        job_dir = FIELD_DOCS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "estimate.pdf")  # Close so ReportLab can write to it

        def build_pdf():
            doc = self._get_doc_template(filepath, job_id=job_id)
            story = []
            
            # Styles
            normal_style = self.styles["Normal"]
            
            # Custom Legal Style
            legal_style = ParagraphStyle(
                name="LegalDisclaimer",
                parent=self.styles["Normal"],
                fontSize=8,
                leading=10,
                textColor=colors.dimgrey,
            )
            
            # --- 1. Metadata ---
            story.append(Paragraph("<b>Roofing Estimate</b>", self.styles["Heading2"]))
            story.append(Paragraph(f"<b>Job ID:</b> {job_id}", normal_style))
            story.append(Spacer(1, 12))
            
            # --- 3. Materials ---
            story.append(Paragraph("<b>Scope of Work / Materials:</b>", normal_style))
            story.append(Spacer(1, 6))
            materials = data.get("materials", [])
            
            mat_map = {
                "field_shingle_bundles": "Field Shingles (Bundles)",
                "starter_bundles": "Starter Shingles (Bundles)",
                "ridge_cap_bundles": "Ridge Cap (Bundles)",
                "ice_water_rolls": "Ice & Water Shield (Rolls)",
                "underlayment_rolls": "Synthetic Underlayment (Rolls)",
                "drip_edge_pieces": "Drip Edge (Pieces)",
                "vents_count": "Roof Vents (Count)",
                "nails_boxes": "Nails (Boxes)",
                "sealant_tubes": "Sealant (Tubes)"
            }
            
            if materials:
                clean_materials = []
                for m in materials:
                    m_str = str(m)
                    if ":" in m_str:
                        key, val = m_str.split(":", 1)
                        clean_key = mat_map.get(key.strip(), key.strip().replace("_", " ").title())
                        clean_materials.append([clean_key, val.strip()])
                    else:
                        clean_materials.append([m_str, "1"])
                        
                t_data = [["Material", "Quantity"]] + clean_materials
                t = Table(t_data, colWidths=[350, 100])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.white]),
                    ('PADDING', (0,0), (-1,-1), 6)
                ]))
                story.append(t)
            else:
                story.append(Paragraph("No materials specified.", normal_style))
            story.append(Spacer(1, 12))
            
            # --- 4. Total Cost ---
            total_cost = data.get("total_cost", 0.0)
            total_style = ParagraphStyle(
                name="TotalCost",
                parent=normal_style,
                fontSize=14,
                fontName="Helvetica-Bold",
                alignment=2 # 2=TA_RIGHT
            )
            story.append(Paragraph(f"Total Cost: ${total_cost:,.2f}", total_style))
            story.append(Paragraph("(Includes Labor, Material Waste, and Applicable Taxes)", self.custom_styles["FinePrint"]))
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

    async def generate_supplement_pdf(self, report: DiscrepancyReport, narrative: str, job: dict) -> str:
        """
        Generate a Supplement Request PDF including the discrepancy summary and AI narrative.
        Returns the absolute filepath to the temporary PDF.
        """
        job_id = job.get("id", "UNKNOWN")
        log = logger.bind(job_id=job_id)
        log.info("supplement_pdf_generation_started")

        job_dir = FIELD_DOCS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "Supplement_Request.pdf")

        def build_pdf():
            doc = self._get_doc_template(filepath, job_id=job_id)
            story = []
            
            # Styles
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
            
            # --- 1. Title ---
            story.append(Paragraph("<b>SUPPLEMENT REQUEST</b>", self.styles["Heading2"]))
            story.append(Spacer(1, 12))
            
            # --- 2. Metadata ---
            story.append(self._build_metadata_table(job))
            story.append(Spacer(1, 12))
            
            # --- 3. Discrepancy Table ---
            story.append(Paragraph("<b>Summary of Mathematical Variances:</b>", normal_style))
            story.append(Spacer(1, 6))
            
            table_data = [["Category", "EV Value", "SoL Value", "Variance", "Xactimate"]]
            for d in report.discrepancies:
                table_data.append([
                    d.category,
                    f"{d.ev_value:.2f}" if isinstance(d.ev_value, (int, float)) else str(d.ev_value) if d.ev_value is not None else "N/A",
                    f"{d.sol_value:.2f}" if isinstance(d.sol_value, (int, float)) else str(d.sol_value) if d.sol_value is not None else "N/A",
                    f"{d.variance:.2f}" if isinstance(d.variance, (int, float)) else str(d.variance) if d.variance is not None else "N/A",
                    d.xactimate_code if d.xactimate_code else "N/A",
                ])
                
            if len(table_data) > 1:
                t = Table(table_data, colWidths=[130, 70, 70, 80, 100])
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
            
            # --- 4. Narrative & Code Requirements ---
            story.append(Paragraph("<b>Defensive Summary & Code Requirements:</b>", normal_style))
            story.append(Spacer(1, 6))
            
            # Fetch rules and citations from DB
            from app.core.database import get_connection
            conn = get_connection()
            try:
                # Fetch the ice_barrier_required flag from jobs
                job_cursor = conn.execute("SELECT ice_barrier_required, jurisdiction_code_version FROM jobs WHERE id = ?", (job_id,))
                job_row = job_cursor.fetchone()
                ice_barrier_required = bool(job_row["ice_barrier_required"]) if job_row and job_row["ice_barrier_required"] is not None else False
                jurisdiction = job_row["jurisdiction_code_version"] if job_row else "2021_IRC"

                cursor = conn.execute('''
                    SELECT r.citation_text, r.citation_type, r.required_child_code, r.climate_dependent
                    FROM supplement_flags f
                    JOIN supplement_rules r ON f.rule_id = r.id
                    WHERE f.job_id = ? AND f.triggered = 1
                ''', (job_id,))
                rules = cursor.fetchall()
                
                for r in rules:
                    ctype = r["citation_type"]
                    ctext = r["citation_text"]
                    climate_dependent = bool(r["climate_dependent"])
                    
                    # CLIMATE GATE: Defensive second layer. If the rule is marked climate_dependent 
                    # and the job's ice_barrier_required is False/None, block it from PDF.
                    if climate_dependent and not ice_barrier_required:
                        continue
                    
                    if ctype == "IRC":
                        framed = f"Pursuant to {jurisdiction.replace('_', ' ')} Section: {ctext}"
                    elif ctype == "MFG_SPEC":
                        framed = f"Per Manufacturer Installation Warranty Requirements: {ctext}"
                    else:
                        framed = f"Policy Note: {ctext}"
                    story.append(Paragraph(f"• <i>{framed}</i>", narrative_style))
                
                # Fetch Weather
                cursor = conn.execute("SELECT * FROM storm_verifications WHERE job_id = ? LIMIT 1", (job_id,))
                weather = cursor.fetchone()
                if weather:
                    story.append(Spacer(1, 6))
                    story.append(Paragraph(f"<b>Weather Exhibit:</b> {weather['magnitude']}in {weather['event_type']} on {weather['loss_date'][:10]}", normal_style))
                    story.append(Paragraph("<i>Source: NOAA NCEI Database (Pending Live Ingestion)</i>", legal_style))
                    
            except Exception as e:
                log.error("pdf_db_fetch_failed", error=str(e))
            finally:
                conn.close()

            story.append(Spacer(1, 6))
            # Split narrative by newlines into separate paragraphs
            for p in narrative.split("\n"):
                if p.strip():
                    story.append(Paragraph(html.escape(p.strip()), narrative_style))
            story.append(Spacer(1, 24))
            
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

        job_dir = FIELD_DOCS_DIR / job.job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "evidence_grid.pdf")

        def build_pdf():
            doc = self._get_doc_template(filepath, job_id=job.job_id)
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
                    # Render image safely with proportional constraint (max width 300 to fit half page)
                    # FIX: Prevent catastrophic ReportLab OOM crashes by downsampling first
                    from app.workers.inspection_processor import resize_for_pdf
                    from reportlab.lib.utils import ImageReader
                    
                    safe_image_buffer = resize_for_pdf(photo_record.filepath, max_width=800)
                    img = Image(ImageReader(safe_image_buffer), width=300, height=200, kind='proportional')
                    
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
            doc = self._get_doc_template(filepath, job_id=job["id"])
            story = []
            
            # --- 1. Order Details ---
            po_number = f"PO-{job['id'][:8].upper()}-{datetime.date.today().isoformat()}"
            story.append(Paragraph(f"<b>PO Number:</b> {po_number}", self.custom_styles["BodyText"]))
            story.append(Paragraph(f"<b>Supplier:</b> {supplier_name}", self.custom_styles["BodyText"]))
            story.append(Paragraph("<b>Supplier Account #:</b> [TBD - Insert Account Here]", self.custom_styles["BodyText"]))
            story.append(Paragraph("<b>Order Confirmation #:</b> ___________________", self.custom_styles["BodyText"]))
            story.append(Paragraph(f"<b>Order Date:</b> {datetime.date.today().isoformat()}", self.custom_styles["BodyText"]))
            story.append(Paragraph(f"<b>Requested Delivery Date:</b> {delivery_date}", self.custom_styles["BodyText"]))
            story.append(Spacer(1, 12))
            
            story.append(Paragraph("Delivery Information:", self.custom_styles["SectionHeading"]))
            story.append(Paragraph(f"<b>Homeowner:</b> {job['homeowner_name']}", self.custom_styles["BodyText"]))
            story.append(Paragraph(f"<b>Address:</b> {job['address_line1']}, {job['city']}, {job['state']} {job['postal_code']}", self.custom_styles["BodyText"]))
            story.append(Paragraph(f"<b>Claim #:</b> {job.get('claim_number', 'N/A')}", self.custom_styles["BodyText"]))
            story.append(Spacer(1, 18))
            
            # --- 2. BOM Table ---
            story.append(Paragraph("Material Bill of Quantities:", self.custom_styles["SectionHeading"]))
            
            table_data = [["Material Type", "Quantity", "Unit"]]
            
            table_data.append(["Field System", "", ""])
            table_data.append(["  Field Shingles", str(bom.field_shingle_bundles), "Bundles"])
            table_data.append(["  Starter Shingles", str(bom.starter_bundles), "Bundles"])
            table_data.append(["  Hip & Ridge", str(bom.ridge_cap_bundles), "Bundles"])
            
            table_data.append(["Underlayments", "", ""])
            table_data.append(["  Ice & Water Shield", str(bom.ice_water_rolls), "Rolls"])
            table_data.append(["  Synthetic Underlayment", str(bom.underlayment_rolls), "Rolls"])
            
            table_data.append(["Metal & Trim", "", ""])
            table_data.append(["  Drip Edge (10ft)", str(bom.drip_edge_pieces), "Pieces"])
            
            # Build alternating backgrounds, but explicitly style subheaders
            row_colors = [('BACKGROUND', (0, i), (-1, i), colors.whitesmoke if i % 2 == 1 else colors.white) for i in range(1, len(table_data))]
            
            t = Table(table_data, colWidths=[200, 100, 100])
            base_style = [
                ('BACKGROUND', (0,0), (-1,0), colors.grey),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (0,-1), 'LEFT'),
                ('ALIGN', (1,0), (-1,-1), 'RIGHT'), # right align numeric columns
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0,0), (-1,0), 8),
                ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
                
                # Subheaders
                ('BACKGROUND', (0,1), (-1,1), colors.lightgrey),
                ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'),
                ('BACKGROUND', (0,5), (-1,5), colors.lightgrey),
                ('FONTNAME', (0,5), (-1,5), 'Helvetica-Bold'),
                ('BACKGROUND', (0,8), (-1,8), colors.lightgrey),
                ('FONTNAME', (0,8), (-1,8), 'Helvetica-Bold'),
            ]
            t.setStyle(TableStyle(base_style + row_colors))
            story.append(t)
            story.append(Spacer(1, 20))
            
            # --- 3. Special Instructions ---
            story.append(Paragraph("Special Instructions:", self.custom_styles["SectionHeading"]))
            story.append(Paragraph("Deliver to driveway; no yard entry with loaded truck.", self.custom_styles["BodyText"]))
            story.append(Spacer(1, 20))
            story.append(Paragraph("<b>Total Estimated Cost:</b> $___________", self.custom_styles["SectionHeading"]))
            
            doc.build(story)

        try:
            await asyncio.to_thread(build_pdf)
            log.info("material_po_generation_complete", filepath=filepath)
            return filepath
        except Exception as exc:
            log.error("material_po_generation_failed", error=str(exc))
            raise
    async def generate_contingency_agreement(self, job: dict) -> str:
        """Generate a Georgia Insurance Contingency Agreement.
        
        Args:
            job (dict): Job dictionary containing homeowner_name, address_line1, etc.
        """
        job_dir = FIELD_DOCS_DIR / job["id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "contingency_agreement.pdf")

        def build_pdf():
            doc = self._get_doc_template(filepath, job_id=job["id"])
            story = []
            
            story.append(Paragraph("INSURANCE CONTINGENCY AGREEMENT", self.custom_styles["Title"]))
            story.append(Spacer(1, 20))
            
            # --- Metadata Table ---
            story.append(self._build_metadata_table(job))
            story.append(Spacer(1, 15))
            
            story.append(Paragraph("Scope of Work & Payment", self.custom_styles["SectionHeading"]))
            scope_text = "Contractor agrees to repair or replace the roof at the above address. The final scope of work and price shall be strictly determined by the insurance carrier's approved estimate. Any additional work or upgrades require a signed change order."
            story.append(Paragraph(scope_text, self.custom_styles["BodyText"]))
            story.append(Spacer(1, 10))
            
            # --- Boxed Warnings ---
            warning_text = "WARNING: It is a violation of Georgia law (O.C.G.A. § 33-24-59.27) for a contractor to pay, waive, rebate, or promise to pay or rebate all or part of an insurance deductible. The homeowner is strictly responsible for the payment of the deductible."
            story.append(self._box_warning("HB 423 Deductible & Inducement Clause", warning_text, colors.darkred))
            story.append(Spacer(1, 10))
            
            story.append(Paragraph("Public Adjuster Restriction", self.custom_styles["SectionHeading"]))
            pa_text = "The contractor is not a public adjuster and does not represent or negotiate on behalf of the owner for the insurance claim."
            story.append(Paragraph(pa_text, self.custom_styles["BodyText"]))
            story.append(Spacer(1, 10))
            
            cancel_text = "You may cancel this contract within five (5) business days after you receive written notice from your insurer that all or any part of your claim is not a covered loss under your insurance policy."
            story.append(self._box_warning("Statutory Cancellation Disclosure", cancel_text, colors.darkred))
            
            # Signature block
            story.append(self._build_signature_block())
            
            doc.build(story)

        await asyncio.to_thread(build_pdf)
        return filepath

    async def generate_contingency_pdf(self, job: dict, signature_path: str, signer_name: str, ip_address: str) -> str:
        """Generate a basic Legal Contingency document with embedded signature and legal footer."""
        job_id = job.get("id", "UNKNOWN")
        log = logger.bind(job_id=job_id)
        log.info("contingency_pdf_generation_started")

        job_dir = FIELD_DOCS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "contingency_agreement_signed.pdf")

        def build_pdf():
            doc = self._get_doc_template(filepath, job_id=job_id)
            story = []
            
            story.append(Paragraph("INSURANCE CONTINGENCY AGREEMENT", self.custom_styles["Title"]))
            story.append(Spacer(1, 20))
            
            # --- Metadata Table ---
            story.append(self._build_metadata_table(job))
            story.append(Spacer(1, 15))
            
            story.append(Paragraph("Scope of Work & Payment", self.custom_styles["SectionHeading"]))
            scope_text = "Contractor agrees to repair or replace the roof at the above address. The final scope of work and price shall be strictly determined by the insurance carrier's approved estimate. Any additional work or upgrades require a signed change order."
            story.append(Paragraph(scope_text, self.custom_styles["BodyText"]))
            story.append(Spacer(1, 10))
            
            warning_text = "WARNING: It is a violation of Georgia law (O.C.G.A. § 33-24-59.27) for a contractor to pay, waive, rebate, or promise to pay or rebate all or part of an insurance deductible. The homeowner is strictly responsible for the payment of the deductible."
            story.append(self._box_warning("HB 423 Deductible & Inducement Clause", warning_text, colors.darkred))
            story.append(Spacer(1, 20))
            
            # --- Signature ---
            story.append(Paragraph("<b>Homeowner Authorization</b>", self.styles["Heading2"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=12))
            
            try:
                sig_img = Image(str(signature_path), width=300, height=100, kind='proportional')
                story.append(sig_img)
            except Exception as e:
                log.error("signature_render_failed", error=str(e))
                
            story.append(Spacer(1, 10))
            story.append(Paragraph(f"Digitally signed by {signer_name} from IP {ip_address}", self.custom_styles["FinePrint"]))
            
            doc.build(story)

        try:
            await asyncio.to_thread(build_pdf)
            log.info("contingency_pdf_generation_complete", filepath=filepath)
            return filepath
        except Exception as exc:
            log.error("contingency_pdf_generation_failed", error=str(exc))
            raise
    async def generate_notice_of_cancellation(self, job: dict) -> str:
        """
        Generate Georgia statutory Notice of Cancellation.
        """
        job_dir = FIELD_DOCS_DIR / job["id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "notice_of_cancellation.pdf")

        def build_pdf():
            doc = self._get_doc_template(filepath, job_id=job["id"])
            story = []
            
            for copy_type in ["Customer Copy", "Contractor Copy"]:
                story.append(Paragraph(copy_type, self.custom_styles["DocControl"]))
                story.append(Spacer(1, 10))
                
                story.append(Paragraph("NOTICE OF CANCELLATION", self.custom_styles["Title"]))
                story.append(Spacer(1, 12))
                
                # --- Metadata Table ---
                story.append(self._build_metadata_table(job))
                story.append(Spacer(1, 12))
                
                story.append(Paragraph(f"Date of Transaction: {datetime.date.today().isoformat()}", self.custom_styles["BodyText"]))
                story.append(Spacer(1, 12))
                
                statutory_text = (
                    "You may cancel this contract at any time before midnight on the fifth business day after you have received written "
                    "notification from your insurer that all or any part of the claim or contract is not a covered loss under the insurance policy. "
                    "See attached notice of cancellation form for an explanation of this right."
                )
                story.append(Paragraph(statutory_text, self.custom_styles["StatWarning"]))
                story.append(Spacer(1, 20))
                
                story.append(Paragraph("To cancel this transaction, mail or deliver a signed and dated copy of this cancellation notice, or any other written notice, to:<br/><br/><b>WICKHAM ROOFING LLC</b><br/>123 Roofing Lane<br/>Thomasville, GA 31792", self.custom_styles["BodyText"]))
                story.append(Spacer(1, 40))
                story.append(Paragraph("I HEREBY CANCEL THIS TRANSACTION.", self.custom_styles["BodyText"]))
                story.append(Spacer(1, 40))
                
                # Use standard signature block but with specific Homeowner Signature text
                story.append(self._build_signature_block(title1="Homeowner Signature", title2="Contractor Signature"))
                
                if copy_type == "Customer Copy":
                    story.append(PageBreak())
            
            doc.build(story)

        await asyncio.to_thread(build_pdf)
        return filepath

    async def generate_certificate_of_completion(self, job: dict, completion_date: str) -> str:
        """
        Generate Certificate of Completion.
        """
        job_dir = FIELD_DOCS_DIR / job["id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "certificate_of_completion.pdf")

        def build_pdf():
            doc = self._get_doc_template(filepath, job_id=job["id"])
            story = []
            
            story.append(Paragraph("CERTIFICATE OF COMPLETION", self.custom_styles["Title"]))
            story.append(Spacer(1, 12))
            
            # --- Metadata Table ---
            story.append(self._build_metadata_table(job))
            story.append(Spacer(1, 15))
            
            story.append(Paragraph("Work Acceptance & Punch List", self.custom_styles["SectionHeading"]))
            text = (
                f"This document certifies that Wickham Roofing LLC has satisfactorily completed "
                f"all roofing services per the agreed scope of work at the property located at:<br/><br/>"
                f"<b>{job['address_line1']}, {job['city']}, {job['state']} {job['postal_code']}</b><br/><br/>"
                f"for the homeowner, <b>{job['homeowner_name']}</b>, on <b>{completion_date}</b>. "
                f"The homeowner acknowledges that the roof has been inspected, all punch list items have been resolved, and "
                f"all work has been performed in compliance with applicable local and state building codes."
            )
            story.append(Paragraph(text, self.custom_styles["BodyText"]))
            story.append(Spacer(1, 15))
            
            story.append(Paragraph("WAIVER AND RELEASE OF LIEN AND PAYMENT BOND RIGHTS UPON FINAL PAYMENT", self.custom_styles["SectionHeading"]))
            story.append(Paragraph("STATE OF GEORGIA<br/>COUNTY OF THOMAS", self.custom_styles["BodyText"]))
            story.append(Spacer(1, 10))
            address_str = f"{job['address_line1']}, {job['city']}, {job['state']} {job['postal_code']}"
            lien_text = (
                "THE UNDERSIGNED MECHANIC AND/OR MATERIALMAN HAS BEEN EMPLOYED BY WICKHAM ROOFING LLC "
                "TO FURNISH ROOFING MATERIALS AND LABOR FOR THE CONSTRUCTION OF IMPROVEMENTS KNOWN AS "
                f"ROOF REPLACEMENT WHICH IS LOCATED IN THE CITY OF {job['city'].upper()}, COUNTY OF THOMAS, "
                f"AND IS OWNED BY {job['homeowner_name'].upper()} AND MORE PARTICULARLY DESCRIBED AS FOLLOWS:<br/><br/>"
                f"{address_str.upper()}<br/><br/>"
                "UPON THE RECEIPT OF THE SUM OF $__________, THE MECHANIC AND/OR MATERIALMAN WAIVES AND RELEASES "
                "ANY AND ALL LIENS OR CLAIMS OF LIENS IT HAS UPON THE FOREGOING DESCRIBED PROPERTY OR ANY RIGHTS "
                "AGAINST ANY LABOR AND/OR MATERIAL BOND ON ACCOUNT OF LABOR OR MATERIALS, OR BOTH, FURNISHED BY "
                "THE UNDERSIGNED TO OR ON ACCOUNT OF SAID CONTRACTOR FOR SAID PROPERTY.<br/><br/>"
                f"GIVEN UNDER HAND AND SEAL THIS {datetime.date.today().day} DAY OF {datetime.date.today().strftime('%B').upper()}, {datetime.date.today().year}."
            )
            story.append(Paragraph(lien_text, self.custom_styles["BodyText"]))
            story.append(Spacer(1, 15))
            
            warranty_text = (
                "Wickham Roofing LLC guarantees the workmanship of the installation for a "
                "period of 5 years from the date of completion. Material warranties are provided directly by the manufacturer "
                "and any claims regarding defective materials must be directed to the manufacturer."
            )
            story.append(self._box_warning("Warranty Disclaimer", warranty_text, colors.lightgrey))
            story.append(Spacer(1, 20))
            
            story.append(self._build_signature_block(title1="Homeowner Signature", title2="Wickham Roofing LLC Representative", include_witness=True))
            
            doc.build(story)

        await asyncio.to_thread(build_pdf)
        return filepath

    async def generate_monthly_financial_summary(self, month: int, year: int) -> str:
        """Generate a professional PDF summary for the specified month."""
        from app.core.database import get_monthly_financials
        
        log = logger.bind(month=month, year=year)
        log.info("monthly_summary_generation_started")
        
        filepath = str(FIELD_DOCS_DIR / f"Monthly_Financial_Summary_{year}_{month:02d}.pdf")
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        def build_pdf():
            doc = self._get_doc_template(filepath, top_margin=120, job_id="MONTHLY")
            story = []
            
            story.append(Paragraph(f"Monthly Financial Summary - {year}-{month:02d}", self.custom_styles["Title"]))
            story.append(Spacer(1, 20))
            
            jobs = get_monthly_financials(month, year)
            
            if not jobs:
                story.append(Paragraph("No INVOICED or CLOSED jobs found for this period.", self.custom_styles["BodyText"]))
                doc.build(story)
                return
            
            total_rev = 0.0
            total_cogs = 0.0
            total_comm = 0.0
            
            # Details Table
            table_data = [["Job ID", "Homeowner", "Revenue", "Costs", "Margin"]]
            
            for j in jobs:
                rev = j.get("revenue", 0.0)
                mat = j.get("material_cost", 0.0)
                lab = j.get("labor_cost", 0.0)
                oh_pct = j.get("overhead_pct", 0.0)
                comm_pct = j.get("canvasser_commission_pct", 0.0)
                
                oh_val = oh_pct if oh_pct < 1 else (oh_pct / 100.0)
                comm_val = comm_pct if comm_pct < 1 else (comm_pct / 100.0)
                
                cogs = mat + lab + ((mat+lab)*oh_val)
                comm = rev * comm_val
                margin = rev - cogs - comm
                
                total_rev += rev
                total_cogs += cogs
                total_comm += comm
                
                table_data.append([
                    j["id"][:8], 
                    j["homeowner_name"], 
                    f"${rev:,.2f}", 
                    f"${cogs:,.2f}", 
                    f"${margin:,.2f}"
                ])
                
            total_margin = total_rev - total_cogs - total_comm
            
            # Summary Block
            summary_data = [
                ["Total Revenue:", f"${total_rev:,.2f}"],
                ["Total COGS:", f"${total_cogs:,.2f}"],
                ["Total Commissions:", f"${total_comm:,.2f}"],
                ["Total Gross Margin:", f"${total_margin:,.2f}"]
            ]
            
            st = Table(summary_data, colWidths=[150, 150], hAlign='LEFT')
            st.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
                ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
                ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                ('PADDING', (0,0), (-1,-1), 6)
            ]))
            
            story.append(Paragraph("Executive Summary", self.custom_styles["SectionHeading"]))
            story.append(st)
            story.append(Spacer(1, 20))
            
            # Details Block
            story.append(Paragraph("Job Details", self.custom_styles["SectionHeading"]))
            
            dt = Table(table_data, colWidths=[80, 150, 80, 80, 80])
            dt.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.grey),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('ALIGN', (0,0), (1,-1), 'LEFT'),
                ('ALIGN', (2,0), (-1,-1), 'RIGHT'), # explicit right-align Revenue, Costs, Margin
                ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.white]),
                ('PADDING', (0,0), (-1,-1), 6)
            ]))
            story.append(dt)
            
            doc.build(story)
            
        await asyncio.to_thread(build_pdf)
        log.info("monthly_summary_generation_complete", filepath=filepath)
        return filepath

    async def generate_inspection_letter(self, job: dict, ev_data: dict, inspection_summary: dict) -> str:
        """Generate a formal inspection letter combining measurements and photo evidence."""
        job_id = job.get("id", "UNKNOWN")
        job_dir = FIELD_DOCS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "inspection_letter.pdf")
        
        def build_pdf():
            doc = self._get_doc_template(filepath, top_margin=120, job_id=job_id)
            story = []
            
            story.append(Paragraph("FORMAL ROOF INSPECTION REPORT", self.custom_styles["Title"]))
            story.append(Spacer(1, 20))
            
            # Metadata with new inspector fields
            address = f"{job.get('address_line1', '')}, {job.get('city', '')}, {job.get('state', '')} {job.get('postal_code', '')}"
            meta_data = [
                ["Job ID:", job.get("id", "N/A")],
                ["Homeowner:", job.get("homeowner_name", "N/A")],
                ["Property Address:", address],
                ["Inspector:", job.get("inspector_name") or "Pending Assignment"],
                ["Inspection Date:", job.get("inspection_date") or "TBD"]
            ]
            
            t = Table(meta_data, colWidths=[120, 380])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
                ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
                ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                ('PADDING', (0,0), (-1,-1), 6),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ]))
            story.append(t)
            story.append(Spacer(1, 20))
            
            story.append(Paragraph("Measurement Summary", self.custom_styles["SectionHeading"]))
            total_sf = ev_data.get("total_area_sf", 0)
            sq = f"{total_sf / 100.0:.1f}" if isinstance(total_sf, (int, float)) and total_sf > 0 else "N/A"
            ridge = ev_data.get("ridge_lf", "N/A")
            valleys = ev_data.get("valley_lf", "N/A")
            eaves = ev_data.get("eaves_lf", "N/A")
            
            meas_data = [
                ["Measurement Type", "Value"],
                ["Total Squares", f"{sq} SQ"],
                ["Ridges", f"{ridge} LF"],
                ["Valleys", f"{valleys} LF"],
                ["Eaves (Drip Edge)", f"{eaves} LF"]
            ]
            meas_table = Table(meas_data, colWidths=[250, 150])
            meas_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.white]),
                ('PADDING', (0,0), (-1,-1), 6)
            ]))
            story.append(meas_table)
            story.append(Spacer(1, 15))
            
            story.append(Paragraph("Photo Evidence Summary", self.custom_styles["SectionHeading"]))
            damage_count = inspection_summary.get("damage_count", 0)
            predominant = inspection_summary.get("predominant_damage_type", "None detected")
            severity = inspection_summary.get("severity", "Unknown")
            
            photo_data = [
                ["Metric", "Assessment"],
                ["Detected Damage Count", str(damage_count)],
                ["Predominant Damage Type", str(predominant)],
                ["Overall Severity", str(severity)]
            ]
            photo_table = Table(photo_data, colWidths=[250, 150])
            photo_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.white]),
                ('PADDING', (0,0), (-1,-1), 6)
            ]))
            story.append(photo_table)
            story.append(Spacer(1, 15))
            
            if "notes" in inspection_summary:
                story.append(Paragraph(f"Notes: {inspection_summary['notes']}", self.custom_styles["BodyText"]))
                story.append(Spacer(1, 15))
            
            if job.get("inspection_notes"):
                story.append(Paragraph("Inspector Notes", self.custom_styles["SectionHeading"]))
                story.append(Paragraph(job["inspection_notes"], self.custom_styles["BodyText"]))
                story.append(Spacer(1, 15))
            
            legal_text = (
                "This report constitutes a preliminary assessment of apparent roof conditions on the date of inspection. "
                "It does not serve as an engineering report, nor does it guarantee insurance coverage."
            )
            story.append(self._box_warning("Disclaimer", legal_text, colors.darkred))
            story.append(Spacer(1, 20))
            
            story.append(self._build_signature_block(title1="Inspector Signature", title2="Homeowner Acknowledgment"))
            
            doc.build(story)
            
        await asyncio.to_thread(build_pdf)
        return filepath
