from app.services.pdf.invoice import InvoiceGenerator
from app.services.pdf.supplement import SupplementGenerator
from app.services.pdf.commission import CommissionGenerator
from app.services.pdf.documents import DocumentsGenerator
from app.services.pdf.inspection_report import InspectionReportGenerator

class PDFGenerator(InvoiceGenerator, SupplementGenerator, CommissionGenerator, DocumentsGenerator, InspectionReportGenerator):
    pass
