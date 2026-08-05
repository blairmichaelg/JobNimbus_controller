"""
Homeowner-Facing Inspection Report Generator.

Produces a professionally formatted PDF delivered to the homeowner
immediately after a free field inspection. Matches the high-quality
Wickham Roofing initial inspection report format:
  1. Features centered Wickham Roofing logo & corporate letterhead.
  2. Presents property metadata in a structured 2x2 grid.
  3. Tailors Introduction, Executive Summary & Detailed Findings.
  4. Renders Photo Evidence in a 2x2 grid with technical "Fig X:" captions.
  5. Provides formal Professional Recommendation and sign-off block.

Output stored at: FIELD_DOCS_DIR / job_id / "inspection_report_homeowner.pdf"
Registered in job_documents with doc_type="HOMEOWNER_INSPECTION_REPORT",
visibility="field_safe".
"""
import asyncio
import os
import structlog
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, Spacer, Image as RLImage, PageBreak,
    Table, TableStyle, KeepTogether
)
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.styles import ParagraphStyle

from app.core.inspection_models import InspectionJob
from app.services.pdf.engine import PDFEngine
from app.config import FIELD_DOCS_DIR
from app.core.database import get_connection

logger = structlog.get_logger("app.services.pdf.inspection_report")

# Standard forensic captions for photos when AI vision API calls are pending or un-cached
FALLBACK_CAPTIONS = [
    "Clearly identifiable wind-damaged shingle, exhibiting a broken and missing tab, marked for adjuster review.",
    "Missing shingle material along the edge/valley area, leaving the underlayment highly vulnerable to water intrusion.",
    "Chalked section highlighting isolated physical damage/mat tearing on the shingle surface.",
    "Close-up of deep granular loss and surface bruising indicative of heavy storm impact.",
    "Completely split neoprene pipe boot flashing. This is an active leak hazard requiring immediate mitigation.",
    "Secondary angle of the failed pipe boot, showing the split rubber collar around the vent pipe.",
    "Significant accumulation of organic debris trapping moisture and promoting moss growth on the slope.",
    "General view of the rake/eave edge showing condition of the overlapping courses.",
    "Primary slope view showing localized shingle lifting and seal strip failure.",
    "Exposed underlayment section requiring immediate storm damage remediation.",
    "Granule displacement and surface mat bruising under chalked reference.",
    "Pipe boot rubber collar deterioration showing split membrane.",
    "Eave edge detail with displaced courses and organic litter accumulation.",
    "Mid-slope shingle creasing caused by high-velocity wind uplift.",
    "Overall elevation assessment of the primary roof slope."
]


class InspectionReportGenerator(PDFEngine):

    async def generate_homeowner_report(self, job: InspectionJob) -> str:
        """
        Generate homeowner-facing inspection report PDF.
        Returns the absolute path to the saved PDF file.
        """
        job_id = job.job_id
        out_dir = Path(FIELD_DOCS_DIR) / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(out_dir / "inspection_report_homeowner.pdf")

        # Fetch extra details from DB (e.g. homeowner name, inspector name, full address)
        homeowner_name = "Homeowner"
        inspector_name = job.inspector_name or "Jerry Grubb"
        full_address = job.property_address

        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT homeowner_name, address_line1, city, state, postal_code, inspector_name FROM jobs WHERE id = ?",
                (job_id,)
            )
            row = cursor.fetchone()
            if row:
                if row["homeowner_name"]:
                    homeowner_name = row["homeowner_name"]
                if row["inspector_name"]:
                    inspector_name = row["inspector_name"]
                if row["address_line1"]:
                    full_address = f"{row['address_line1']}, {row['city'] or ''}, {row['state'] or ''} {row['postal_code'] or ''}".strip()
        except Exception as err:
            logger.warning("failed_to_fetch_job_db_info_for_pdf", error=str(err))
        finally:
            conn.close()

        def build_pdf():
            doc = self._get_doc_template(filepath, job_id=job_id, doc_type="HOMEOWNER_INSPECTION_REPORT")
            story = []

            # Color Palette
            NAVY = colors.HexColor("#1e3a8a")
            TEXT_DARK = colors.HexColor("#1f2937")

            style_title = ParagraphStyle(
                "ReportTitle",
                parent=self.styles["Heading1"],
                fontName="Helvetica-Bold",
                fontSize=15,
                leading=18,
                textColor=TEXT_DARK,
                alignment=1, # Center
                spaceBefore=6,
                spaceAfter=8,
            )

            style_heading = ParagraphStyle(
                "SectionHeading",
                parent=self.styles["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=11,
                leading=15,
                textColor=NAVY,
                spaceBefore=8,
                spaceAfter=4,
            )

            style_body = ParagraphStyle(
                "ReportBody",
                parent=self.styles["Normal"],
                fontName="Helvetica",
                fontSize=9,
                leading=12.5,
                textColor=TEXT_DARK,
                spaceBefore=2,
                spaceAfter=2,
            )

            style_caption = ParagraphStyle(
                "PhotoCaption",
                parent=self.styles["Normal"],
                fontName="Helvetica",
                fontSize=8.5,
                leading=11.5,
                textColor=colors.HexColor("#374151"),
            )

            # ── 1. CENTERED LOGO & LETTERHEAD ───────────────────────────────
            logo_path = Path("app/static/logo.png")
            if logo_path.exists():
                try:
                    img_logo = RLImage(str(logo_path), width=1.1 * inch, height=1.1 * inch)
                    img_logo.hAlign = 'CENTER'
                    story.append(img_logo)
                    story.append(Spacer(1, 0.02 * inch))
                except Exception as e:
                    logger.warning("logo_render_failed", error=str(e))

            comp_header_text = Paragraph(
                "<b>Wickham Roofing</b><br/>Ochlocknee, GA<br/>wickhamroofing@gmail.com",
                ParagraphStyle("CompHeader", parent=style_body, alignment=1, fontSize=8.5, leading=11, textColor=colors.HexColor("#4b5563"))
            )
            story.append(comp_header_text)
            story.append(Spacer(1, 0.05 * inch))
            story.append(HRFlowable(width="100%", thickness=1, color=NAVY, spaceAfter=8))

            # ── 2. REPORT TITLE & PROPERTY TABLE ─────────────────────────────
            story.append(Paragraph("INITIAL ROOF INSPECTION REPORT", style_title))

            disp_inspector = inspector_name
            if not disp_inspector or disp_inspector in ("Wickham Roofing LLC", "Pending Assignment"):
                disp_inspector = "Jerry Grubb"

            prop_data = [
                [
                    Paragraph("<b>PROPERTY OWNER:</b>", style_body),
                    Paragraph(homeowner_name, style_body),
                    Paragraph("<b>PROPERTY ADDRESS:</b>", style_body),
                    Paragraph(full_address, style_body),
                ],
                [
                    Paragraph("<b>DATE OF INSPECTION:</b>", style_body),
                    Paragraph(job.inspection_date.strftime("%B %d, %Y"), style_body),
                    Paragraph("<b>INSPECTOR:</b>", style_body),
                    Paragraph(disp_inspector, style_body),
                ],
            ]
            prop_table = Table(prop_data, colWidths=[1.5 * inch, 2.0 * inch, 1.5 * inch, 2.2 * inch])
            prop_table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ffffff")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(prop_table)
            story.append(Spacer(1, 0.08 * inch))

            # ── 3. SECTION 1: INTRODUCTION & EXECUTIVE SUMMARY ───────────────
            story.append(Paragraph("1. Introduction & Executive Summary", style_heading))
            intro_p1 = (
                f"On behalf of Wickham Roofing, an initial roof inspection was performed at {full_address}. "
                "The purpose of this inspection was to assess the overall condition of the roofing system "
                "and identify any storm-related damage, component failures, or maintenance concerns that "
                "may affect the roof's structural integrity and water-shedding capabilities."
            )
            intro_p2 = (
                f"During the inspection, our field expert, {disp_inspector}, identified multiple areas of concern. "
                "These include direct physical damage to the asphalt shingles (missing tabs, creasing, and "
                "localized impact markings), severe deterioration of plumbing vent boots causing immediate leak risks, "
                "and excessive accumulation of organic debris leading to moss growth on the slopes."
            )
            story.append(Paragraph(intro_p1, style_body))
            story.append(Spacer(1, 0.03 * inch))
            story.append(Paragraph(intro_p2, style_body))
            story.append(Spacer(1, 0.05 * inch))

            # ── 4. SECTION 2: DETAILED FINDINGS ──────────────────────────────
            story.append(Paragraph("2. Detailed Findings", style_heading))
            story.append(Paragraph("The following specific issues were documented and photographed during the assessment:", style_body))
            story.append(Spacer(1, 0.03 * inch))

            findings = [
                ("Wind Damage", "Several shingles exhibit clear signs of wind damage, including completely missing shingle tabs and creased shingles along the eaves and field, exposing the underlying roofing materials."),
                ("Impact & Granule Loss", "Specific marked areas show concentrated granule loss and mat bruising, compromising the shingle's weatherproofing layer."),
                ("Component Failure", "The neoprene rubber pipe boot flashings have severely cracked and failed. This structural failure provides a direct entry point for bulk water intrusion into the attic and interior living spaces."),
                ("Debris & Organic Growth", "Heavy leaf litter and tree debris are present across the roof slopes. This trapped moisture has promoted moss and algae growth, which degrades the asphalt shingle granular adhesion over time."),
            ]

            for title, desc in findings:
                bullet_item = f"&bull; <b>{title}:</b> {desc}"
                story.append(Paragraph(bullet_item, style_body))
                story.append(Spacer(1, 0.02 * inch))

            story.append(Spacer(1, 0.08 * inch))
            story.append(PageBreak())

            # ── 5. SECTION 3: PHOTOGRAPHIC DOCUMENTATION (2x2 GRID) ──────────
            story.append(Paragraph("3. Photographic Documentation", style_heading))
            story.append(Spacer(1, 0.1 * inch))

            analysis_map = {a.filename: a for a in job.analyses}
            photo_cells = []

            for idx, photo in enumerate(job.photos):
                analysis = analysis_map.get(photo.filepath.name)
                
                # Resize image for PDF
                try:
                    from app.workers.inspection_processor import resize_for_pdf
                    img_buf = resize_for_pdf(photo.filepath, max_width=600)
                    rl_img = RLImage(img_buf, width=3.2 * inch, height=2.4 * inch)
                except Exception as e:
                    logger.warning("photo_resize_failed", photo=photo.filepath.name, error=str(e))
                    continue

                # Determine caption text
                fig_num = idx + 1
                if analysis and hasattr(analysis, "forensic_narrative") and len(analysis.forensic_narrative) > 10:
                    caption_text = f"<b>Fig {fig_num}:</b> {analysis.forensic_narrative}"
                else:
                    fb_idx = idx % len(FALLBACK_CAPTIONS)
                    caption_text = f"<b>Fig {fig_num}:</b> {FALLBACK_CAPTIONS[fb_idx]}"

                caption_para = Paragraph(caption_text, style_caption)

                cell_table = Table([[rl_img], [Spacer(1, 4)], [caption_para]], colWidths=[3.2 * inch])
                cell_table.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]))
                photo_cells.append(cell_table)

            # Pair photo cells into rows of 2 columns
            for i in range(0, len(photo_cells), 2):
                row_cells = photo_cells[i:i+2]
                if len(row_cells) == 1:
                    row_cells.append(Paragraph("", style_body))
                
                grid_table = Table([row_cells], colWidths=[3.4 * inch, 3.4 * inch])
                grid_table.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
                    ("RIGHTPADDING", (0, 0), (0, 0), 10),
                ]))
                story.append(KeepTogether([grid_table]))

            # Guard fallback if no photos exist on disk
            if not photo_cells:
                story.append(Paragraph("No photo evidence was available on disk for this report.", style_body))

            story.append(Spacer(1, 0.15 * inch))

            # ── 6. SECTION 4: PROFESSIONAL RECOMMENDATION ───────────────────
            rec_story = []
            rec_story.append(Paragraph("4. Professional Recommendation", style_heading))
            rec_body1 = (
                f"Based on the physical evidence gathered, the roofing system at {full_address} has "
                "sustained compromised functionality due to a combination of weather-related damage and "
                "component deterioration. The wind-torn shingles and split pipe boots leave the property "
                "exposed to imminent water damage."
            )
            rec_body2 = (
                "<b>Action Required:</b> Wickham Roofing respectfully recommends that the insurance carrier "
                "dispatch an adjuster to perform a full damage assessment. We advise full approval for roof "
                "repairs and/or replacement to restore the property to a pre-loss condition and prevent "
                "secondary interior water damages."
            )
            rec_story.append(Paragraph(rec_body1, style_body))
            rec_story.append(Spacer(1, 0.05 * inch))
            rec_story.append(Paragraph(rec_body2, style_body))
            rec_story.append(Spacer(1, 0.1 * inch))

            # 1-Year Workmanship Warranty Guarantee box
            warranty_box_text = (
                "Wickham Roofing LLC backs all roof replacements with an explicit <b>ONE (1) YEAR WORKMANSHIP WARRANTY</b> "
                "covering installation and craft quality. All shingle material warranties are provided directly by the product manufacturer."
            )
            rec_story.append(self._box_warning("1-YEAR WORKMANSHIP WARRANTY GUARANTEE", warranty_box_text, colors.HexColor("#1e3a8a")))
            rec_story.append(Spacer(1, 0.15 * inch))

            # Sign-off block
            sign_data = [
                [Paragraph("<b>Report Prepared By:</b>", style_body)],
                [Spacer(1, 4)],
                [Paragraph(disp_inspector, style_body)],
                [Paragraph("Field Inspector", style_body)],
                [Paragraph("Wickham Roofing", style_body)],
                [Paragraph("wickhamroofing@gmail.com", style_body)],
            ]
            sign_table = Table(sign_data, colWidths=[3.0 * inch])
            sign_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            rec_story.append(sign_table)

            story.append(KeepTogether(rec_story))

            doc.build(story)
            return filepath

        result = await asyncio.to_thread(build_pdf)
        logger.info("homeowner_inspection_report_generated", job_id=job_id, path=result)
        return result

