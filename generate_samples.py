import os
import shutil
import asyncio
from pathlib import Path
import sys
import sqlite3

# Ensure imports work from the root directory
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.core.supplement_models import MaterialBOM
from app.services.pdf_generator import PDFGenerator
from app.core.database import insert_job_document, init_db, upsert_financials, get_connection

async def main():
    print("==================================================")
    print(" Wickham Roofing V4 - Mock PDF Generator")
    print("==================================================\n")

    # 1. Setup Output Directory
    sample_dir = Path("sample_pdfs").resolve()
    sample_dir.mkdir(parents=True, exist_ok=True)
    print(f"[*] Ensuring output directory exists: {sample_dir}")

    # 2. Setup Mock Data
    mock_job = {
        "id": "demo_job_1",
        "homeowner_name": "Scott Wickham",
        "address_line1": "123 Peachtree Lane",
        "city": "Thomasville",
        "state": "GA",
        "postal_code": "31792",
        "claim_number": "TEST-998877",
        "insurer_name": "State Farm"
    }

    mock_bom = MaterialBOM(
        field_shingle_bundles=45,
        starter_bundles=3,
        ridge_cap_bundles=4,
        ice_water_rolls=2,
        underlayment_rolls=5,
        drip_edge_pieces=12,
        vents_count=0,
        nails_boxes=0,
        sealant_tubes=0
    )

    # Init DB and insert fake financials for the monthly report
    try:
        init_db()
        conn = get_connection()
        try:
            conn.execute("INSERT OR IGNORE INTO jobs (id, homeowner_name, address_line1, city, state, postal_code, phone, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         ("demo_job_1", "Scott Wickham", "123 Peachtree Lane", "Thomasville", "GA", "31792", "555-0199", "INVOICED", "2026-07-01 12:00:00"))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
            
        upsert_financials(
            job_id="demo_job_1",
            revenue=15000.0,
            carrier_rcv=16000.0,
            material_cost=4500.0,
            labor_cost=3500.0,
            overhead_pct=10.0,
            canvasser_commission_pct=10.0,
            permits_fee=150.0
        )
    except Exception as e:
        print(f"[*] Warning: Could not mock database for monthly report: {e}")

    generator = PDFGenerator()

    # 3. Generate Notice of Cancellation
    print("[*] Generating Notice of Cancellation...")
    noc_temp_path = await generator.generate_notice_of_cancellation(mock_job)
    noc_final = sample_dir / "Notice_of_Cancellation_Mock.pdf"
    shutil.move(noc_temp_path, str(noc_final))

    # 4. Generate Certificate of Completion
    print("[*] Generating Certificate of Completion...")
    coc_temp_path = await generator.generate_certificate_of_completion(mock_job, "2026-07-01")
    coc_final = sample_dir / "Certificate_of_Completion_Mock.pdf"
    shutil.move(coc_temp_path, str(coc_final))

    # 5. Generate Contingency Agreement
    print("[*] Generating Contingency Agreement...")
    ca_temp_path = await generator.generate_contingency_agreement(mock_job)
    ca_final = sample_dir / "Contingency_Agreement_Mock.pdf"
    shutil.move(ca_temp_path, str(ca_final))

    # 6. Generate Material PO
    print("[*] Generating Material PO...")
    po_temp_path = await generator.generate_material_po(
        mock_job, 
        mock_bom, 
        supplier_name="ABC Supply Co", 
        delivery_date="2026-06-30"
    )
    po_final = sample_dir / "Material_PO_Mock.pdf"
    shutil.move(po_temp_path, str(po_final))

    # 7. Generate Monthly Financial Summary
    print("[*] Generating Monthly Financial Summary...")
    monthly_path = await generator.generate_monthly_financial_summary(7, 2026)
    monthly_final = sample_dir / "Monthly_Financial_Summary_Mock.pdf"
    shutil.move(monthly_path, str(monthly_final))

    # Cleanup the field_docs demo folder if it exists
    try:
        shutil.rmtree(Path("field_docs/demo_job_1"))
    except OSError:
        pass

    # 8. Output Results
    print("\n[SUCCESS] Mock PDFs generated successfully!\n")
    print(f"Contingency Agreement: {ca_final}")
    print(f"Notice of Cancellation: {noc_final}")
    print(f"Certificate of Completion: {coc_final}")
    print(f"Material PO: {po_final}")
    print(f"Monthly Financial Summary: {monthly_final}\n")

if __name__ == "__main__":
    asyncio.run(main())
