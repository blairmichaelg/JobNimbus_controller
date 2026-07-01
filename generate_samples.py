import os
import shutil
import asyncio
from pathlib import Path
import sys

# Ensure imports work from the root directory
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.core.supplement_models import MaterialBOM
from app.services.pdf_generator import PDFGenerator

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
    # This one saves to field_docs/{job_id}/... by default, so we move it to sample_pdfs/
    po_temp_path = await generator.generate_material_po(
        mock_job, 
        mock_bom, 
        supplier_name="ABC Supply Co", 
        delivery_date="2026-06-30"
    )
    po_final = sample_dir / "Material_PO_Mock.pdf"
    shutil.move(po_temp_path, str(po_final))

    # Cleanup the field_docs demo folder if it exists
    try:
        shutil.rmtree(Path("field_docs/demo_job_1"))
    except OSError:
        pass

    # 7. Output Results
    print("\n[SUCCESS] Mock PDFs generated successfully!\n")
    print(f"Contingency Agreement: {ca_final}")
    print(f"Notice of Cancellation: {noc_final}")
    print(f"Certificate of Completion: {coc_final}")
    print(f"Material PO: {po_final}\n")

if __name__ == "__main__":
    asyncio.run(main())
