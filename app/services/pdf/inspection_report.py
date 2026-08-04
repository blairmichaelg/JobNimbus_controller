"""
Homeowner-Facing Inspection Report Generator.

Produces a professionally formatted PDF delivered to the homeowner
immediately after a free field inspection. This document:
  1. Presents Wickham Roofing's findings in plain language.
  2. Provides AI-captioned photo evidence suitable for insurance company review.
  3. Shows the Condition Index score so the homeowner understands severity.
  4. Gives clear "What To Do Next" instructions for filing their claim.

Output stored at: FIELD_DOCS_DIR / job_id / "inspection_report_homeowner.pdf"
Registered in job_documents with doc_type="HOMEOWNER_INSPECTION_REPORT",
visibility="field_safe" so the rep can access it on their phone.
"""
import asyncio
import structlog
from pathlib import Path
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, Spacer, Image as RLImage, PageBreak,
    Table, TableStyle, KeepTogether
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from app.core.inspection_models import InspectionJob, Severity, calculate_condition_index
from app.services.pdf.engine import PDFEngine
from app.config import FIELD_DOCS_DIR

logger = structlog.get_logger("app.services.pdf.inspection_report")


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

        condition = calculate_condition_index(job)

        def build_pdf():
            doc = self._get_doc_template(filepath, job_id=job_id, doc_type="HOMEOWNER_INSPECTION_REPORT")
            story = []

            # ── COVER PAGE ───────────────────────────────────────────────────
            story.append(Paragraph("<b>ROOF INSPECTION REPORT</b>", self.custom_styles.get("Title", self.styles["Title"])))
            story.append(Spacer(1, 0.2 * inch))

            # Property info table
            prop_data = [
                ["Property:", job.property_address],
                ["Inspection Date:", job.inspection_date.strftime("%B %d, %Y")],
                ["Inspector:", job.inspector_name],
                ["Photos Reviewed:", str(job.total_photos)],
            ]
            prop_table = Table(prop_data, colWidths=[1.8 * inch, 4.5 * inch])
            prop_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ]))
            story.append(prop_table)
            story.append(Spacer(1, 0.3 * inch))

            # ── CONDITION INDEX SCORE BOX ────────────────────────────────────
            grade_color = {
                "A": colors.HexColor("#2e7d32"),
                "B": colors.HexColor("#558b2f"),
                "C": colors.HexColor("#f57f17"),
                "D": colors.HexColor("#e65100"),
                "F": colors.HexColor("#b71c1c"),
            }.get(condition.grade, colors.HexColor("#333333"))

            # hexval property returns "0xRRGGBB" — strip "0x" and prepend "#" for CSS compatibility
            grade_hex = ("#" + grade_color.hexval()[2:]) if hasattr(grade_color, "hexval") else "#333333"
            score_data = [[
                Paragraph(
                    f'<font size="32" color="{grade_hex}"><b>{condition.score}/100 — Grade {condition.grade}</b></font>',
                    self.custom_styles.get("BodyText", self.styles["Normal"])
                ),
            ]]
            score_table = Table(score_data, colWidths=[6.3 * inch])
            score_table.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 1.5, grade_color),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f9f9f9")),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ]))
            story.append(score_table)
            story.append(Spacer(1, 0.15 * inch))

            # Condition flags plain-language summary
            flag_map = {
                "full_replacement_recommended": "⚠ Full roof replacement is recommended based on the inspection findings.",
                "complex_peril_combination": "⚠ Both hail and wind damage were detected — this is a complex claim.",
                "high_supplement_potential": "⚠ Significant damage indicators suggest the insurance estimate may be supplemented.",
                "severe_aging_detected": "⚠ Severe granule loss and aging were detected across multiple surfaces.",
            }
            for flag in condition.flags:
                if flag in flag_map:
                    story.append(Paragraph(
                        flag_map[flag],
                        self.custom_styles.get("BodyText", self.styles["Normal"])
                    ))
                    story.append(Spacer(1, 0.05 * inch))

            story.append(PageBreak())

            # ── PHOTO EVIDENCE GRID ──────────────────────────────────────────
            story.append(Paragraph(
                "<b>Photo Evidence</b>",
                self.custom_styles.get("SectionHeader", self.styles["Heading2"])
            ))
            story.append(Spacer(1, 0.15 * inch))

            # Build analysis map for quick lookup by filename
            analysis_map = {a.filename: a for a in job.analyses}

            for photo in job.photos:
                analysis = analysis_map.get(photo.filepath.name)
                if not analysis:
                    continue

                try:
                    from app.workers.inspection_processor import resize_for_pdf
                    img_buf = resize_for_pdf(photo.filepath, max_width=600)
                    rl_img = RLImage(img_buf, width=3.0 * inch, height=2.25 * inch)
                except Exception as e:
                    logger.warning("photo_resize_failed", photo=photo.filepath.name, error=str(e))
                    continue

                # Severity badge color
                sev_color = {
                    "severe": "#b71c1c",
                    "moderate": "#e65100",
                    "minor": "#f57f17",
                    "none": "#2e7d32",
                }.get(analysis.severity.value, "#333333")

                caption_lines = [
                    f'<b>{photo.filepath.name}</b>',
                    f'Damage: <font color="{sev_color}"><b>{analysis.damage_type.value.upper()} — {analysis.severity.value.upper()}</b></font>',
                    f'Confidence: {int(analysis.confidence * 100)}%',
                    "",
                    analysis.forensic_narrative,
                ]
                if analysis.hail_hits_visible:
                    caption_lines.append("-  Hail impact marks visible")
                if analysis.crease_marks:
                    caption_lines.append("-  Wind-lift crease marks visible")
                if analysis.granule_loss:
                    caption_lines.append("-  Significant granule loss")
                if analysis.exposed_fiberglass:
                    caption_lines.append("-  Exposed fiberglass mat detected")

                caption_para = Paragraph(
                    "<br/>".join(caption_lines),
                    self.custom_styles.get("BodyText", self.styles["Normal"])
                )

                photo_row = Table(
                    [[rl_img, caption_para]],
                    colWidths=[3.2 * inch, 3.1 * inch]
                )
                photo_row.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (1, 0), (1, 0), 12),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#dddddd")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                ]))
                story.append(KeepTogether([photo_row, Spacer(1, 0.05 * inch)]))

            # Guard: empty photo section fallback
            if not any(analysis_map.get(p.filepath.name) for p in job.photos):
                story.append(Paragraph(
                    "No photo evidence was available for this report.",
                    self.custom_styles.get("BodyText", self.styles["Normal"])
                ))

            story.append(PageBreak())

            # ── NEXT STEPS FOR HOMEOWNER ─────────────────────────────────────
            story.append(Paragraph(
                "<b>What To Do Next</b>",
                self.custom_styles.get("SectionHeader", self.styles["Heading2"])
            ))
            story.append(Spacer(1, 0.1 * inch))

            steps = [
                ("<b>1. Locate your Date of Loss.</b>",
                 "This is the date of the storm or weather event that caused the damage. "
                 "Check local weather reports or ask your Wickham Roofing representative — "
                 "we can verify the storm date using official weather records."),
                ("<b>2. Contact your insurance company.</b>",
                 "Call the claims number on your insurance card. Tell them you have storm "
                 "damage to your roof and provide the date of loss. They will open a claim "
                 "and give you a claim number."),
                ("<b>3. Schedule the adjuster visit.</b>",
                 "Your insurance company will send an adjuster to inspect the property. "
                 "Please notify Wickham Roofing when this appointment is scheduled — "
                 "we strongly recommend having our representative present at the adjuster visit "
                 "to ensure all damage is properly documented."),
                ("<b>4. Keep this report.</b>",
                 "Provide a copy of this inspection report to your adjuster. It documents "
                 "the damage found by Wickham Roofing's AI-assisted inspection system and "
                 "serves as independent evidence supporting your claim."),
                ("<b>5. We handle the rest.</b>",
                 "Once your claim is opened, Wickham Roofing will coordinate measurement "
                 "reports, work directly with your adjuster on the scope of work, and manage "
                 "the entire repair process from start to finish at no out-of-pocket cost "
                 "beyond your deductible."),
            ]

            for heading, body in steps:
                story.append(Paragraph(heading, self.custom_styles.get("BodyText", self.styles["Normal"])))
                story.append(Paragraph(body, self.custom_styles.get("BodyText", self.styles["Normal"])))
                story.append(Spacer(1, 0.15 * inch))

            # Contact footer
            story.append(Spacer(1, 0.2 * inch))
            story.append(Paragraph(
                "Questions? Contact Wickham Roofing at any time.",
                self.custom_styles.get("BodyText", self.styles["Normal"])
            ))

            doc.build(story)
            return filepath

        result = await asyncio.to_thread(build_pdf)
        logger.info("homeowner_inspection_report_generated", job_id=job_id, path=result)
        return result
