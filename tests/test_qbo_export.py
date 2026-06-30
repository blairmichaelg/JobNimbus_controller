"""
Unit tests for the QuickBooks Online (QBO) CSV Export Bridge.
"""

import csv
import pytest
from pathlib import Path

from app.core.supplement_models import InvoiceExport, InvoiceLine
from app.services.qbo_export import export_to_csv, EXPORT_DIR, QBO_ITEMS


@pytest.fixture(autouse=True)
def clean_exports():
    """Ensure a clean export directory for each test."""
    if EXPORT_DIR.exists():
        for f in EXPORT_DIR.glob("*.csv"):
            f.unlink()
    yield


def test_qbo_export_formats_correctly():
    """Verify correct CSV headers and multi-line flattening."""
    export = InvoiceExport(
        invoice_no="INV-1001",
        customer="John Doe",
        invoice_date="2026-06-30",
        due_date="2026-07-30",
        lines=[
            InvoiceLine(
                item="shingle_install",
                description="Install architectural shingles",
                quantity=30.5,
                rate=100.0,
                amount=3050.0
            ),
            InvoiceLine(
                item="tear_off",
                description="Tear off old roof",
                quantity=30.5,
                rate=50.0,
                amount=1525.0
            )
        ]
    )

    filepath = export_to_csv(export)
    
    assert Path(filepath).exists()
    assert Path(filepath).name == "INV-1001_QBO.csv"

    # Read and verify CSV contents
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

        # 1 header + 2 data rows
        assert len(rows) == 3
        
        # Verify headers
        assert rows[0] == [
            "InvoiceNo", "Customer", "InvoiceDate", "DueDate", 
            "Item(Product/Service)", "ItemDescription", "ItemQuantity", "ItemRate", "ItemAmount"
        ]

        # Verify Line 1
        assert rows[1][0] == "INV-1001"
        assert rows[1][1] == "John Doe"
        assert rows[1][4] == QBO_ITEMS["shingle_install"]
        assert rows[1][5] == "Install architectural shingles"
        assert rows[1][6] == "30.50"
        assert rows[1][8] == "3050.00"

        # Verify Line 2 (invoice metadata must be repeated)
        assert rows[2][0] == "INV-1001"
        assert rows[2][1] == "John Doe"
        assert rows[2][4] == QBO_ITEMS["tear_off"]


def test_qbo_export_skips_negative_amounts():
    """QBO rejects negative line items; verify they are skipped."""
    export = InvoiceExport(
        invoice_no="INV-1002",
        customer="Jane Smith",
        invoice_date="2026-06-30",
        due_date="2026-07-30",
        lines=[
            InvoiceLine(
                item="shingle_install",
                description="Valid item",
                quantity=1.0,
                rate=100.0,
                amount=100.0
            ),
            InvoiceLine(
                item="discount",
                description="Negative item",
                quantity=1.0,
                rate=-50.0,
                amount=-50.0
            )
        ]
    )

    filepath = export_to_csv(export)

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

        # 1 header + 1 valid data row (negative skipped)
        assert len(rows) == 2
        assert rows[1][4] == QBO_ITEMS["shingle_install"]


def test_qbo_export_unmapped_item_fallback():
    """Unrecognized item names should pass through unchanged."""
    export = InvoiceExport(
        invoice_no="INV-1003",
        customer="Bob",
        invoice_date="2026-06-30",
        due_date="2026-07-30",
        lines=[
            InvoiceLine(
                item="custom_fee_xyz",
                description="Custom fee",
                quantity=1.0,
                rate=50.0,
                amount=50.0
            )
        ]
    )

    filepath = export_to_csv(export)

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
        
        # 'custom_fee_xyz' is not in QBO_ITEMS, so it should be output literally
        assert rows[1][4] == "custom_fee_xyz"
