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
    async def generate_contingency_pdf(self, job: dict, signature_path: str, signer_name: str, ip_address: str, timestamp_utc: str = "") -> str:
        """Generate a complete Legal Contingency document with embedded signature, legal clauses, and 1-Year Workmanship Warranty."""
        job_id = job.get("id", "UNKNOWN")
        log = logger.bind(job_id=job_id)
        log.info("contingency_pdf_generation_started")

        job_dir = FIELD_DOCS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "contingency_agreement_signed.pdf")

        def build_pdf() -> None:
            doc = self._get_doc_template(filepath, top_margin=120, job_id=job_id, doc_type="CONTINGENCY_SIGNED")
            story = []
            
            story.append(Paragraph("INSURANCE CONTINGENCY & SCOPE AGREEMENT", self.custom_styles["Title"]))
            story.append(Spacer(1, 14))
            
            # --- Metadata Table ---
            story.append(self._build_metadata_table(job))
            story.append(Spacer(1, 14))
            
            # --- Section 1: Scope of Work ---
            story.append(Paragraph("1. Scope of Work & Insurance Authorization", self.custom_styles["SectionHeading"]))
            scope_text = (
                "Contractor (Wickham Roofing LLC) agrees to perform complete roof and exterior restoration services at the property listed above. "
                "The final scope of work, specifications, and contract price shall be strictly determined by the insurance carrier's approved estimate, "
                "plus any Homeowner-requested upgrades or signed change orders. Homeowner hereby authorizes Contractor to inspect property, document storm damage, "
                "verify technical line-item quantities, and communicate directly with insurance adjusters on construction scope and building code compliance matters."
            )
            story.append(Paragraph(scope_text, self.custom_styles["BodyText"]))
            story.append(Spacer(1, 10))
            
            # --- Section 2: 1-Year Workmanship Warranty ---
            warranty_text = (
                "Wickham Roofing LLC provides an explicit <b>ONE (1) YEAR WORKMANSHIP WARRANTY</b> on all labor and installation craft quality from the date "
                "of final project completion. Contractor agrees to repair any installation defects free of charge during the warranty period. "
                "All manufacturer material warranties (shingles, synthetic underlayment, ventilation) are transferred directly to Homeowner upon full payment."
            )
            story.append(self._box_warning("1-YEAR WORKMANSHIP WARRANTY GUARANTEE", warranty_text, colors.HexColor("#1e3a8a")))
            story.append(Spacer(1, 10))
            
            # --- Section 3: HB 423 Georgia Law Deductible Disclosure ---
            warning_text = (
                "WARNING: It is a violation of Georgia law (O.C.G.A. § 33-24-59.27) for a contractor to pay, waive, rebate, or promise to pay or rebate "
                "all or any portion of an insurance deductible. Homeowner is strictly responsible for payment of the insurance deductible in full."
            )
            story.append(self._box_warning("HB 423 Deductible Compliance Disclosure (O.C.G.A. § 33-24-59.27)", warning_text, colors.darkred))
            story.append(Spacer(1, 10))
            
            # --- Section 4: Terms, Representation & Cancellation Rights ---
            story.append(Paragraph("2. Terms, Representation & Statutory Cancellation Right", self.custom_styles["SectionHeading"]))
            terms_text = (
                "<b>Public Adjuster Disclosure:</b> Contractor is not acting as a licensed public adjuster and does not represent or negotiate legal claims on behalf of Homeowner.<br/><br/>"
                "<b>Statutory Right to Cancel (O.C.G.A. § 43-14-14):</b> Homeowner has the statutory right to cancel this contract without penalty at any time before midnight "
                "on the fifth (5th) business day after receiving written notification from the insurer that all or any part of the claim is not a covered loss under the policy.<br/><br/>"
                "<b>Default & Liquidated Overhead:</b> If Homeowner breaches this contract after insurance approval without statutory cause, Homeowner agrees to pay liquidated damages "
                "equal to 15% of the approved claim total to reimburse Contractor for administrative, technical, and pre-construction expenses."
            )
            story.append(Paragraph(terms_text, self.custom_styles["BodyText"]))
            story.append(Spacer(1, 16))
            
            # --- Signature ---
            story.append(Paragraph("<b>Homeowner Authorization & Digital Execution</b>", self.styles["Heading2"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=10))
            
            try:
                sig_img = Image(str(signature_path), width=280, height=80, kind='proportional')
                story.append(sig_img)
            except Exception as e:
                log.error("signature_render_failed", error=str(e))
                
            story.append(Spacer(1, 8))
            time_str = f" on {timestamp_utc}" if timestamp_utc else ""
            story.append(Paragraph(f"Digitally signed & verified by <b>{signer_name}</b> from IP address <b>{ip_address}</b>{time_str}", self.custom_styles["FinePrint"]))
            
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

        def build_pdf() -> None:
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

    async def generate_retail_contract_pdf(self, job: dict, signature_path: str, signer_name: str, ip_address: str, total_price_cents: int, deposit_cents: int, scope_description: str, timestamp_utc: str = "") -> str:
        """Generate a Retail Sales Contract document."""
        job_id = job.get("id", "UNKNOWN")
        log = logger.bind(job_id=job_id)
        log.info("retail_contract_pdf_generation_started")

        job_dir = FIELD_DOCS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "retail_contract_signed.pdf")

        def build_pdf() -> None:
            doc = self._get_doc_template(filepath, job_id=job_id, doc_type="RETAIL_CONTRACT_SIGNED")
            story = []
            
            story.append(Paragraph("RESIDENTIAL ROOFING CONTRACT", self.custom_styles["Title"]))
            story.append(Spacer(1, 20))
            
            # --- Metadata Table ---
            story.append(self._build_metadata_table(job))
            story.append(Spacer(1, 15))
            
            # --- Parties ---
            story.append(Paragraph("Parties", self.custom_styles["SectionHeading"]))
            parties_text = f"This contract is made between Wickham Roofing LLC (Contractor) and {job.get('homeowner_name', 'UNKNOWN')} (Homeowner)."
            story.append(Paragraph(parties_text, self.custom_styles["BodyText"]))
            story.append(Spacer(1, 10))
            
            # --- Scope of Work ---
            story.append(Paragraph("Scope of Work", self.custom_styles["SectionHeading"]))
            story.append(Paragraph(html.escape(scope_description), self.custom_styles["BodyText"]))
            story.append(Spacer(1, 10))
            
            # --- Payment Terms ---
            story.append(Paragraph("Payment Terms", self.custom_styles["SectionHeading"]))
            
            total_dollars = f"${total_price_cents / 100:,.2f}"
            deposit_dollars = f"${deposit_cents / 100:,.2f}"
            balance_dollars = f"${(total_price_cents - deposit_cents) / 100:,.2f}"
            
            payment_data = [
                ["Total Contract Price:", total_dollars],
                ["Deposit Due at Signing:", deposit_dollars],
                ["Balance Due Upon Completion:", balance_dollars]
            ]
            ptable = Table(payment_data, colWidths=[200, 150])
            ptable.setStyle(TableStyle([
                ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
                ('BACKGROUND', (0,0), (-1,-1), colors.whitesmoke),
                ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                ('PADDING', (0,0), (-1,-1), 6),
            ]))
            story.append(ptable)
            story.append(Spacer(1, 10))
            story.append(Paragraph("Final payment is due in full upon substantial completion of work, prior to contractor's departure from the job site, unless otherwise agreed in writing.", self.custom_styles["BodyText"]))
            story.append(Spacer(1, 10))
            
            # --- Warranty ---
            story.append(Paragraph("Workmanship Warranty", self.custom_styles["SectionHeading"]))
            warranty_text = "Wickham Roofing CRM provides a 1-year workmanship warranty on all full roof replacements. Material warranties are provided directly by the manufacturer."
            story.append(Paragraph(warranty_text, self.custom_styles["BodyText"]))
            story.append(Spacer(1, 15))
            
            # --- Right to Cancel ---
            cancel_notice = "NOTICE OF RIGHT TO CANCEL: You, the buyer, may cancel this transaction at any time before midnight of the THIRD BUSINESS DAY after the date of this transaction. See the attached Notice of Cancellation form for an explanation of this right."
            story.append(Paragraph(cancel_notice, self.custom_styles["StatWarning"]))
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
            time_str = f" on {timestamp_utc}" if timestamp_utc else ""
            story.append(Paragraph(f"Digitally signed by {signer_name} from IP {ip_address}{time_str}", self.custom_styles["FinePrint"]))
            
            doc.build(story)

        try:
            await asyncio.to_thread(build_pdf)
            log.info("retail_contract_pdf_generation_complete", filepath=filepath)
            return filepath
        except Exception as exc:
            log.error("retail_contract_pdf_generation_failed", error=str(exc))
            raise

    async def generate_retail_notice_of_cancellation(self, job: dict) -> str:
        """
        Generate General Georgia statutory Notice of Cancellation for Retail Sales.
        """
        job_dir = FIELD_DOCS_DIR / job["id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "retail_notice_of_cancellation.pdf")

        def build_pdf() -> None:
            doc = self._get_doc_template(filepath, job_id=job["id"], doc_type="RETAIL_NOTICE_OF_CANCELLATION")
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
                    "You may cancel this transaction, without any penalty or obligation, "
                    "within THREE BUSINESS DAYS from the above date. To cancel this "
                    "transaction, mail or deliver a signed and dated copy of this "
                    "cancellation notice, or any other written notice, to Wickham Roofing "
                    "LLC at the address below, not later than midnight of the third "
                    "business day after the date of this transaction. If you cancel by "
                    "mail, notice must be postmarked by that deadline."
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

        def build_pdf() -> None:
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
                "Wickham Roofing CRM provides a 1-year workmanship warranty on all full roof replacements. "
                "Material warranties are provided directly by the manufacturer."
            )
            story.append(self._box_warning("Warranty Disclaimer", warranty_text, colors.lightgrey))
            story.append(Spacer(1, 20))
            
            story.append(self._build_signature_block(title1="Homeowner Signature", title2="Wickham Roofing LLC Representative", include_witness=True))
            
            doc.build(story)

        await asyncio.to_thread(build_pdf)
        return filepath


    async def generate_contingency_agreement(self, job: dict) -> str:
        """Generate a complete Georgia Insurance Contingency Agreement.
        
        Args:
            job (dict): Job dictionary containing homeowner_name, address_line1, etc.
        """
        job_dir = FIELD_DOCS_DIR / job["id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(job_dir / "contingency_agreement.pdf")

        def build_pdf() -> None:
            doc = self._get_doc_template(filepath, top_margin=120, job_id=job["id"], doc_type="CONTINGENCY")
            story = []
            
            story.append(Paragraph("INSURANCE CONTINGENCY & SCOPE AGREEMENT", self.custom_styles["Title"]))
            story.append(Spacer(1, 14))
            
            # --- Metadata Table ---
            story.append(self._build_metadata_table(job))
            story.append(Spacer(1, 14))
            
            # --- Section 1: Scope of Work ---
            story.append(Paragraph("1. Scope of Work & Insurance Authorization", self.custom_styles["SectionHeading"]))
            scope_text = (
                "Contractor (Wickham Roofing LLC) agrees to perform complete roof and exterior restoration services at the property listed above. "
                "The final scope of work, specifications, and contract price shall be strictly determined by the insurance carrier's approved estimate, "
                "plus any Homeowner-requested upgrades or signed change orders. Homeowner hereby authorizes Contractor to inspect property, document storm damage, "
                "verify technical line-item quantities, and communicate directly with insurance adjusters on construction scope and building code compliance matters."
            )
            story.append(Paragraph(scope_text, self.custom_styles["BodyText"]))
            story.append(Spacer(1, 10))
            
            # --- Section 2: 1-Year Workmanship Warranty ---
            warranty_text = (
                "Wickham Roofing LLC provides an explicit <b>ONE (1) YEAR WORKMANSHIP WARRANTY</b> on all labor and installation craft quality from the date "
                "of final project completion. Contractor agrees to repair any installation defects free of charge during the warranty period. "
                "All manufacturer material warranties (shingles, synthetic underlayment, ventilation) are transferred directly to Homeowner upon full payment."
            )
            story.append(self._box_warning("1-YEAR WORKMANSHIP WARRANTY GUARANTEE", warranty_text, colors.HexColor("#1e3a8a")))
            story.append(Spacer(1, 10))
            
            # --- Section 3: HB 423 Georgia Law Deductible Disclosure ---
            warning_text = (
                "WARNING: It is a violation of Georgia law (O.C.G.A. § 33-24-59.27) for a contractor to pay, waive, rebate, or promise to pay or rebate "
                "all or any portion of an insurance deductible. Homeowner is strictly responsible for payment of the insurance deductible in full."
            )
            story.append(self._box_warning("HB 423 Deductible Compliance Disclosure (O.C.G.A. § 33-24-59.27)", warning_text, colors.darkred))
            story.append(Spacer(1, 10))
            
            # --- Section 4: Terms, Representation & Cancellation Rights ---
            story.append(Paragraph("2. Terms, Representation & Statutory Cancellation Right", self.custom_styles["SectionHeading"]))
            terms_text = (
                "<b>Public Adjuster Disclosure:</b> Contractor is not acting as a licensed public adjuster and does not represent or negotiate legal claims on behalf of Homeowner.<br/><br/>"
                "<b>Statutory Right to Cancel (O.C.G.A. § 43-14-14):</b> Homeowner has the statutory right to cancel this contract without penalty at any time before midnight "
                "on the fifth (5th) business day after receiving written notification from the insurer that all or any part of the claim is not a covered loss under the policy.<br/><br/>"
                "<b>Default & Liquidated Overhead:</b> If Homeowner breaches this contract after insurance approval without statutory cause, Homeowner agrees to pay liquidated damages "
                "equal to 15% of the approved claim total to reimburse Contractor for administrative, technical, and pre-construction expenses."
            )
            story.append(Paragraph(terms_text, self.custom_styles["BodyText"]))
            story.append(Spacer(1, 16))
            
            # Signature block
            story.append(self._build_signature_block(title1="Homeowner Signature", title2="Wickham Roofing LLC Representative"))
            
            doc.build(story)

        await asyncio.to_thread(build_pdf)
        return filepath


