import os
import shutil
import asyncio
from pathlib import Path
import sys
import sqlite3

# Ensure imports work from the root directory
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(root_dir)
from app.core.supplement_models import MaterialBOM
from app.services.pdf_generator import PDFGenerator
from app.core.database import init_db, upsert_financials, get_connection
from app.services.ai_service import AIService
from app.services.pdf_extractor import extract_eagleview_data
from app.core.reconciliation import reconcile
from app.core.complexity import compute_complexity_score, calculate_dynamic_waste

async def main():
    print("==================================================")
    print(" Wickham Roofing V4 - Mock PDF Generator")
    print("==================================================\n")

    # 1. Setup Output Directory
    sample_dir = (Path(root_dir) / "sample_pdfs").resolve()
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
            conn.execute("DELETE FROM jobs WHERE id = ?", ("demo_job_1",))
            conn.execute("INSERT INTO jobs (id, homeowner_name, address_line1, city, state, postal_code, phone, status, inspector_name, inspection_date, inspection_notes, claim_number, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         ("demo_job_1", "Scott Wickham", "123 Peachtree Lane", "Thomasville", "GA", "31792", "555-0199", "INVOICED", "Michael Wickham - Lic # GA-99887", "2026-06-30 09:15:00", "Observed significant hail damage to the west-facing slopes.", "TEST-998877", "2026-07-01 12:00:00"))
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

    # 8. Generate Inspection Letter
    print("[*] Generating Inspection Letter...")
    ev_data = {"total_squares": 32.5, "ridges": 40, "valleys": 25, "eaves": 120}
    inspection_summary = {"damage_count": 14, "predominant_damage_type": "Hail Hits (3/4in)", "severity": "High", "notes": "Customer requested urgent tarping."}
    # fetch the job from db to get metadata
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", ("demo_job_1",))
        row = cursor.fetchone()
        mock_job_with_meta = dict(row) if row else mock_job
    finally:
        conn.close()
    
    insp_path = await generator.generate_inspection_letter(mock_job_with_meta, ev_data, inspection_summary)
    insp_final = sample_dir / "Inspection_Letter_Mock.pdf"
    shutil.move(insp_path, str(insp_final))

    # 9. E2E AI PDF Generation (Estimate & Supplement)
    print("[*] Running E2E AI Extraction for Estimate and Supplement...")
    print("    -> Note: This will call the live Gemini API and takes ~15-30 seconds.")
    
    # Paths to the samples
    ev_pdf = Path(root_dir) / "samples" / "EagleView-Sample-Premium_Roof_Report.pdf"
    sol_pdf = Path(root_dir) / "samples" / "xactimate-sample.pdf"
    
    if ev_pdf.exists() and sol_pdf.exists():
        ai_service = AIService()
        
        print("    -> Extracting EagleView data...")
        ev_data_obj = await extract_eagleview_data(ev_pdf)
        
        print("    -> Extracting Statement of Loss (Live AI Call)...")
        sol_data_obj = await ai_service.extract_sol_from_pdf(str(sol_pdf))
        
        print("    -> Reconciling & Computing Waste...")
        score = compute_complexity_score(ev_data_obj)
        waste = calculate_dynamic_waste(score)
        report = reconcile(ev_data_obj, sol_data_obj, "demo_job_1", waste_factor=waste)
        
        print("    -> Generating Supplement Narrative (Live AI Call)...")
        # In a real run, codes would be fetched from RAG, we'll pass a dummy string for the mock
        codes = "IRC R905.2.7 Underlayment application. IRC R905.2.8.2 Valleys."
        narrative = await ai_service.generate_supplement_narrative(report, codes)
        
        print("    -> Generating Estimate PDF...")
        # Prepare data for estimate
        bom_dict = report.material_bom.model_dump()
        materials_list = [f"{k}: {v}" for k, v in bom_dict.items() if v and isinstance(v, (int, float)) and v > 0]
        # In a real run, total_cost is calculated dynamically. We'll put a mock amount.
        estimate_data = {"materials": materials_list, "total_cost": 15450.00}
        est_path = await generator.generate_estimate_pdf(estimate_data, "demo_job_1")
        est_final = sample_dir / "Estimate_Mock.pdf"
        shutil.move(est_path, str(est_final))
        
        print("    -> Generating Supplement Request PDF...")
        supp_path = await generator.generate_supplement_pdf(report, narrative, mock_job_with_meta)
        supp_final = sample_dir / "Supplement_Request_Mock.pdf"
        shutil.move(supp_path, str(supp_final))
    else:
        print("    -> SKIPPED: Sample PDFs not found in samples/ directory.")
        est_final = None
        supp_final = None

    # Cleanup the field_docs demo folder if it exists
    try:
        shutil.rmtree(Path(root_dir) / "data" / "field_docs" / "demo_job_1")
    except Exception:
        try:
            shutil.rmtree(Path(root_dir) / "field_docs" / "demo_job_1")
        except Exception:
            pass

    # 10. Output Results
    print("\n[SUCCESS] Mock PDFs generated successfully!\n")
    print(f"Contingency Agreement: {ca_final}")
    print(f"Notice of Cancellation: {noc_final}")
    print(f"Certificate of Completion: {coc_final}")
    print(f"Material PO: {po_final}")
    print(f"Monthly Financial Summary: {monthly_final}")
    print(f"Inspection Letter: {insp_final}")
    if est_final and supp_final:
        print(f"Estimate: {est_final}")
        print(f"Supplement Request: {supp_final}\n")

if __name__ == "__main__":
    asyncio.run(main())
