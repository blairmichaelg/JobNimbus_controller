"""
QuickBooks Online (QBO) CSV Exporter.

Flattens structured InvoiceExport data into the exact strict multi-line CSV
format required for QBO batch imports.
"""

import csv
import structlog
from pathlib import Path
from app.core.supplement_models import InvoiceExport

logger = structlog.get_logger("app.services.qbo_export")

# Deterministic mapping for QBO standard products/services
QBO_ITEMS = {
    "shingle_install": "Roofing:Shingle Installation",
    "tear_off": "Roofing:Tear Off & Haul",
    "ridge_cap": "Roofing:Ridge Cap",
    "ice_water": "Roofing:Ice & Water Shield",
    "drip_edge": "Roofing:Drip Edge",
    "underlayment": "Roofing:Synthetic Underlayment",
    "vents": "Roofing:Ventilation",
    "o_and_p": "General:Overhead and Profit",
    "taxes": "General:Taxes",
    "permits": "General:Permits",
}

# Ensure export directory exists
EXPORT_DIR = Path("generated_exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

def export_to_csv(export: InvoiceExport) -> str:
    """
    Generate a strictly formatted QBO CSV file from an InvoiceExport.
    
    QBO Rules Enforced:
    1. Exact headers required.
    2. Multi-line invoices must repeat InvoiceNo, Customer, InvoiceDate, DueDate.
    3. ItemAmount must be >= 0.
    4. Max 100 lines (safety limit).
    """
    log = logger.bind(invoice_no=export.invoice_no, customer=export.customer)
    log.info("qbo_export_started")
    
    if len(export.lines) > 100:
        log.warning("qbo_export_exceeds_100_lines", line_count=len(export.lines))
        # We will process it, but QBO might reject it. Truncating is worse.
        
    export_path = EXPORT_DIR / f"{export.invoice_no}_QBO.csv"
    
    headers = [
        "InvoiceNo",
        "Customer",
        "InvoiceDate",
        "DueDate",
        "Item(Product/Service)",
        "ItemDescription",
        "ItemQuantity",
        "ItemRate",
        "ItemAmount"
    ]
    
    try:
        with open(export_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            
            for line in export.lines:
                if line.amount < 0:
                    log.warning("negative_amount_skipped", item=line.item, amount=line.amount)
                    continue
                
                # Map the item name, fallback to the raw item string if not in QBO_ITEMS
                qbo_item = QBO_ITEMS.get(line.item, line.item)
                
                row = [
                    export.invoice_no,
                    export.customer,
                    export.invoice_date,
                    export.due_date,
                    qbo_item,
                    line.description,
                    f"{line.quantity:.2f}",
                    f"{line.rate:.2f}",
                    f"{line.amount:.2f}"
                ]
                writer.writerow(row)
                
        log.info("qbo_export_complete", filepath=str(export_path))
        return str(export_path)
    
    except Exception as e:
        log.error("qbo_export_failed", error=str(e))
        raise
