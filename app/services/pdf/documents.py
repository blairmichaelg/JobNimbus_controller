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

class DocumentsGenerator(PDFEngine):
    async def generate_contingency_pdf(self, job: dict, signature_path: str, signer_name: str, ip_address: str) -> str:
        """Generate a basic Legal Contingency document with embedded signature and legal footer."""
        job_id = job.get("id", "UNKNOWN")
        log = logger.bind(job_id=job_id)
        log.info("contingency_pdf_generation_started")

        job_dir = FIELD_DOCS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "contingency_agreement_signed.pdf")

        def build_pdf():
            """
            Build Pdf functionality.
            
            Returns:
                Any: The resulting output.
            """
            doc = self._get_doc_template(filepath, job_id=job_id, doc_type="CONTINGENCY_SIGNED")
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
            """
            Build Pdf functionality.
            
            Returns:
                Any: The resulting output.
            """
            doc = self._get_doc_template(filepath, job_id=job["id"], doc_type="NOTICE_OF_CANCELLATION")
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
            """
            Build Pdf functionality.
            
            Returns:
                Any: The resulting output.
            """
            doc = self._get_doc_template(filepath, job_id=job["id"], doc_type="CERTIFICATE_OF_COMPLETION")
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


    async def generate_contingency_agreement(self, job: dict) -> str:
        """Generate a Georgia Insurance Contingency Agreement.
        
        Args:
            job (dict): Job dictionary containing homeowner_name, address_line1, etc.
        """
        job_dir = FIELD_DOCS_DIR / job["id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "contingency_agreement.pdf")

        def build_pdf():
            """
            Build Pdf functionality.
            
            Returns:
                Any: The resulting output.
            """
            doc = self._get_doc_template(filepath, job_id=job["id"], doc_type="CONTINGENCY")
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


