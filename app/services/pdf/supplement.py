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
import hashlib

from app.core.supplement_models import DiscrepancyReport, MaterialBOM
from app.core.inspection_models import InspectionJob
from pathlib import Path

logger = structlog.get_logger("app.services.pdf")
from app.services.pdf.constants import COMPANY_NAME, COMPANY_PHONE, COMPANY_EMAIL, FIELD_DOCS_DIR




from app.services.pdf.engine import PDFEngine

class SupplementGenerator(PDFEngine):
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
            """
            Build Pdf functionality.
            
            Returns:
                Any: The resulting output.
            """
            doc = self._get_doc_template(filepath, job_id=job.job_id, doc_type="EVIDENCE_GRID")
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


    async def generate_inspection_letter(self, job: dict, ev_data: dict, inspection_summary: dict) -> str:
        """Generate a formal inspection letter combining measurements and photo evidence."""
        job_id = job.get("id", "UNKNOWN")
        job_dir = FIELD_DOCS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "inspection_letter.pdf")
        
        def build_pdf():
            """
            Build Pdf functionality.
            
            Returns:
                Any: The resulting output.
            """
            doc = self._get_doc_template(filepath, top_margin=120, job_id=job_id, doc_type="INSPECTION_LETTER")
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


    async def generate_rebuttal_letter(
        self,
        job: dict,
        denial_text: str,
        rebuttal_narrative: str
    ) -> str:
        """
        Generate a formal Rebuttal Letter PDF.
        Returns the permanent vault path.
        """
        job_id = job.get("id", "UNKNOWN")
        log = logger.bind(job_id=job_id)
        log.info("rebuttal_pdf_generation_started")

        job_dir = FIELD_DOCS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "Rebuttal_Letter.pdf")

        def build_pdf():
            """
            Build Pdf functionality.
            
            Returns:
                Any: The resulting output.
            """
            import html as _html
            doc = self._get_doc_template(filepath,
                                         job_id=job_id)
            story = []

            story.append(Paragraph(
                "SUPPLEMENT REBUTTAL LETTER",
                self.custom_styles["Title"]
            ))
            story.append(Spacer(1, 12))
            story.append(self._build_metadata_table(job))
            story.append(Spacer(1, 16))

            story.append(Paragraph(
                "<b>CARRIER DENIAL SUMMARY (VERBATIM):</b>",
                self.custom_styles["SectionHeading"]
            ))
            denial_style = ParagraphStyle(
                "DenialQuote",
                parent=self.styles["Normal"],
                fontSize=9,
                leftIndent=20,
                rightIndent=20,
                textColor=colors.darkred,
                backColor=colors.lightyellow,
                borderPad=6,
            )
            for line in denial_text.split("\n"):
                if line.strip():
                    story.append(Paragraph(
                        _html.escape(line.strip()),
                        denial_style
                    ))
            story.append(Spacer(1, 16))

            story.append(Paragraph(
                "<b>CONTRACTOR REBUTTAL:</b>",
                self.custom_styles["SectionHeading"]
            ))
            story.append(HRFlowable(
                width="100%", thickness=0.5,
                color=colors.black, spaceAfter=10
            ))
            narrative_style = ParagraphStyle(
                "RebuttalBody",
                parent=self.styles["Normal"],
                fontSize=10,
                leading=14,
                spaceBefore=4,
                spaceAfter=4,
            )
            for para in rebuttal_narrative.split("\n"):
                if para.strip():
                    story.append(Paragraph(
                        _html.escape(para.strip()),
                        narrative_style
                    ))

            story.append(Spacer(1, 30))
            story.append(self._build_signature_block(
                title1="Authorized Contractor Representative",
                title2="Date"
            ))
            doc.build(story)

        try:
            await asyncio.to_thread(build_pdf)
            log.info("rebuttal_pdf_generation_complete",
                     filepath=filepath)
            return filepath
        except Exception as exc:
            log.error("rebuttal_pdf_generation_failed",
                      error=str(exc))
            raise


    async def generate_escalation_letter(
        self,
        job: dict,
        days_elapsed: int,
        narrative: str,
    ) -> str:
        """
        Generate a formal Second Request / Notice of Intent to Appraise PDF.

        Args:
            job: Full job record dict.
            days_elapsed: Number of days since supplement was submitted.
            narrative: AI-generated letter body text.

        Returns:
            str: Absolute path to the generated PDF file.
        """
        job_id = job.get("id", "UNKNOWN")
        job_dir = FIELD_DOCS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "Escalation_Demand_Letter.pdf")

        def build_pdf():
            """
            Build Pdf functionality.
            
            Returns:
                Any: The resulting output.
            """
            doc = self._get_doc_template(filepath, job_id=job_id, doc_type="ESCALATION_LETTER")
            story = []

            story.append(
                Paragraph(
                    "SECOND REQUEST \u2014 NOTICE OF INTENT TO APPRAISE",
                    self.custom_styles["Title"],
                )
            )
            story.append(Spacer(1, 8))
            story.append(self._build_metadata_table(job))
            story.append(Spacer(1, 16))

            # Red SLA warning banner
            warning_table = Table(
                [[
                    f"\u26a0  {days_elapsed} DAYS WITHOUT CARRIER RESPONSE "
                    f"\u2014 APPRAISAL PENDING"
                ]],
                colWidths=[450],
            )
            warning_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.darkred),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 13),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ])
            )
            story.append(warning_table)
            story.append(Spacer(1, 12))

            story.append(
                Paragraph("VIA ELECTRONIC SUBMISSION", self.custom_styles["BodyText"])
            )
            story.append(Spacer(1, 12))

            for paragraph in narrative.split("\n\n"):
                if paragraph.strip():
                    story.append(
                        Paragraph(paragraph.strip(), self.custom_styles["BodyText"])
                    )
                    story.append(Spacer(1, 10))

            story.append(Spacer(1, 24))
            story.append(
                self._build_signature_block(
                    title1="Authorized Representative \u2014 Wickham Roofing",
                    title2="Date",
                )
            )
            doc.build(story)

        await asyncio.to_thread(build_pdf)
        return filepath

    async def generate_supplement_pdf(self, report: DiscrepancyReport, narrative: str, job: dict, db_context: dict) -> str:
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
            """
            Build Pdf functionality.
            
            Returns:
                Any: The resulting output.
            """
            doc = self._get_doc_template(filepath, job_id=job_id, doc_type="SUPPLEMENT")
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
            
            # Fetch rules and citations from DB context
            try:
                ice_barrier_required = db_context.get("ice_barrier_required", False)
                jurisdiction = db_context.get("jurisdiction_code_version", "2021_IRC")
                rules = db_context.get("rules", [])
                
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
                
                weather = db_context.get("weather")
                if weather:
                    story.append(Spacer(1, 6))
                    story.append(Paragraph(f"<b>Weather Exhibit:</b> {weather['magnitude']}in {weather['event_type']} on {weather['loss_date'][:10]}", normal_style))
                    story.append(Paragraph("<i>Source: NOAA NCEI Database (Pending Live Ingestion)</i>", legal_style))
                    
            except Exception as e:
                log.error("pdf_db_context_read_failed", error=str(e))

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


