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

class CommissionGenerator(PDFEngine):
    async def generate_commission_statement(
        self,
        job: dict,
        commission_data: dict
    ) -> str:
        """
        Generate Commission Statement functionality.
        
        Args:
                job (dict): job parameter.
                commission_data (dict): commission_data parameter.
        
        Returns:
            str: The resulting output.
        """
        job_id   = job.get("id", "UNKNOWN")
        job_dir  = FIELD_DOCS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(
            job_dir / "Commission_Statement.pdf"
        )

        def build_pdf():
            """
            Build Pdf functionality.
            
            Returns:
                Any: The resulting output.
            """
            doc   = self._get_doc_template(
                filepath, job_id=job_id, doc_type="COMMISSION_STATEMENT"
            )
            story = []

            story.append(Paragraph(
                "INDEPENDENT CONTRACTOR "
                "COMMISSION STATEMENT",
                self.custom_styles["Title"]
            ))
            story.append(Spacer(1, 8))
            story.append(
                self._build_metadata_table(job)
            )
            story.append(Spacer(1, 16))

            story.append(Paragraph(
                f"<b>Canvasser:</b> "
                f"{commission_data['canvasser_name']}",
                self.custom_styles["BodyText"]
            ))
            story.append(Spacer(1, 10))

            rows = [
                ["Line Item", "Amount"],
                ["Total Contract Revenue",
                 f"${commission_data['revenue_val']:,.2f}"],
                ["Less: Material Cost",
                 f"(${commission_data['material_cost_val']:,.2f})"],
                ["Less: Labor Cost",
                 f"(${commission_data['labor_cost_val']:,.2f})"],
                ["Less: Overhead",
                 f"(${commission_data['overhead_amount']:,.2f})"],
                ["Gross Profit",
                 f"${commission_data['gross_profit']:,.2f}"],
                ["Commission Rate",
                 f"{commission_data['commission_pct']*100:.1f}%"],
                ["COMMISSION EARNED",
                 f"${commission_data['commission_amount']:,.2f}"],
            ]
            t = Table(rows, colWidths=[300, 150])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0),
                 colors.darkblue),
                ('TEXTCOLOR', (0,0), (-1,0),
                 colors.white),
                ('FONTNAME', (0,0), (-1,0),
                 'Helvetica-Bold'),
                ('BACKGROUND', (0,-1), (-1,-1),
                 colors.darkgreen),
                ('TEXTCOLOR', (0,-1), (-1,-1),
                 colors.white),
                ('FONTNAME', (0,-1), (-1,-1),
                 'Helvetica-Bold'),
                ('FONTSIZE', (0,-1), (-1,-1), 12),
                ('GRID', (0,0), (-1,-1), 0.5,
                 colors.black),
                ('ALIGN', (1,0), (1,-1), 'RIGHT'),
                ('ROWBACKGROUNDS', (0,1), (-1,-2),
                 [colors.white, colors.lightgrey]),
                ('PADDING', (0,0), (-1,-1), 8),
            ]))
            story.append(t)
            story.append(Spacer(1, 24))

            story.append(
                self._build_signature_block(
                    title1=(
                        "Authorized Signature — "
                        "Wickham Roofing"
                    ),
                    title2="Date"
                )
            )
            story.append(Spacer(1, 12))
            story.append(
                self._build_signature_block(
                    title1=(
                        "Contractor Signature — "
                        f"{commission_data['canvasser_name']}"
                    ),
                    title2="Date Received"
                )
            )
            doc.build(story)

        await asyncio.to_thread(build_pdf)
        return filepath


