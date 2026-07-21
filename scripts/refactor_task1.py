import os
from pathlib import Path

def main():
    root = Path("c:/Users/Michael/projects/JobNimbus_controller")
    pipeline_path = root / "app" / "core" / "pipeline.py"
    office_routes_path = root / "app" / "api" / "office_routes.py"
    
    # 1. Add generate_material_order_pipeline to pipeline.py
    with open(pipeline_path, "a") as f:
        f.write('''
async def generate_material_order_pipeline(job_id: str, supplier_name: str, delivery_date: str) -> dict[str, Any]:
    from app.services.ai_service import AIService
    from app.services.pdf_generator import PDFGenerator
    from app.core.database import _fetch_job_sync, insert_material_order
    from app.config import FIELD_DOCS_DIR
    import asyncio
    
    job_dir = FIELD_DOCS_DIR / job_id
    pdf_path = job_dir / "eagleview.pdf"
    if not pdf_path.exists():
        raise ValueError("EagleView PDF not found. Cannot generate PO.")
        
    ev_data, _ = await extract_eagleview_data(pdf_path)
    sol_pdf_path = job_dir / "statement_of_loss.pdf"
    if sol_pdf_path.exists():
        ai_svc = AIService()
        sol = await ai_svc.extract_sol_from_pdf(str(sol_pdf_path), job_id=job_id)
    else:
        sol = StatementOfLoss(line_items=[], overhead_and_profit_included=True)
        
    report = await asyncio.to_thread(reconcile, ev_data, sol, job_id, 0.15)
    bom = report.material_bom
    
    job_dict = await asyncio.to_thread(_fetch_job_sync, job_id)
    if not job_dict:
        raise ValueError("Job not found in database.")
        
    pdf_gen = PDFGenerator()
    await pdf_gen.generate_material_po(job_dict, bom, supplier_name, delivery_date)
    
    await asyncio.to_thread(insert_material_order, job_id, supplier_name, delivery_date, bom.model_dump_json())
    await asyncio.to_thread(update_job_status, job_id, JobStatus.MATERIAL_ORDERED)
    
    return {"status": "success"}
''')

    # 2. Move retail quote logic
    retail_processor_path = root / "app" / "workers" / "retail_quote_processor.py"
    retail_code = retail_processor_path.read_text()
    retail_logic = retail_code.replace('async def process_retail_quote(\n    ctx: dict,\n    job_id: str\n) -> dict:', 'async def run_retail_quote_pipeline(job_id: str) -> dict:')
    retail_logic = retail_logic.replace('logger = structlog.get_logger(\n    "app.workers.retail_quote_processor"\n)', 'logger = structlog.get_logger("app.core.pipeline")')
    retail_logic = retail_logic.replace('import asyncio\nimport structlog\nfrom app.core.database import (\n    get_connection, update_job_status,\n    insert_job_document, get_pricing_ledger, JobStatus\n)\nfrom app.services.pdf_generator import PDFGenerator', '')
    
    with open(pipeline_path, "a") as f:
        f.write('\nfrom app.core.database import get_connection, insert_job_document, get_pricing_ledger\n')
        f.write(retail_logic.replace('"""\nARQ Worker: Retail Quote Generator', '"""\nRetail Quote Generator Pipeline'))
    
    retail_processor_path.write_text('''"""
ARQ Worker: Retail Quote Generator
"""

import structlog
from app.core.pipeline import run_retail_quote_pipeline

logger = structlog.get_logger("app.workers.retail_quote_processor")

async def process_retail_quote(ctx: dict, job_id: str) -> dict:
    return await run_retail_quote_pipeline(job_id)
''')

    # 3. Refactor office_routes.py to use generate_material_order_pipeline
    office_routes_code = office_routes_path.read_text()
    old_material_order = """    job_dir = FIELD_DOCS_DIR / job_id
    pdf_path = job_dir / "eagleview.pdf"
    
    if not pdf_path.exists():
        raise HTTPException(status_code=400, detail="EagleView PDF not found. Cannot generate PO.")
        
    try:
        # Rebuild BOM
        ev_data, _ = await extract_eagleview_data(pdf_path)
        sol_pdf_path = job_dir / "statement_of_loss.pdf"
        if sol_pdf_path.exists():
            from app.services.ai_service import AIService
            ai_svc = AIService()
            sol = await ai_svc.extract_sol_from_pdf(str(sol_pdf_path), job_id=job_id)
        else:
            sol = StatementOfLoss(line_items=[], overhead_and_profit_included=True)
            
        report = await asyncio.to_thread(reconcile, ev_data, sol, job_id, 0.15)
        bom = report.material_bom
        
        # Fetch Homeowner Info
        job_dict = await asyncio.to_thread(_fetch_job_sync, job_id)
        if not job_dict:
            raise HTTPException(status_code=404, detail="Job not found in database.")
            
        # Generate PO PDF
        pdf_gen = PDFGenerator()
        await pdf_gen.generate_material_po(job_dict, bom, payload.supplier_name, payload.delivery_date)
        
        # Insert Record & Update State
        await asyncio.to_thread(insert_material_order, job_id, payload.supplier_name, payload.delivery_date, bom.model_dump_json())
        await asyncio.to_thread(update_job_status, job_id, JobStatus.MATERIAL_ORDERED)
        
        # Trigger Hot Backup
        bg_tasks.add_task(backup_database)
        
        return {"status": "success"}
    except Exception as e:
        logger.error("material_order_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to process material order")"""
        
    new_material_order = """    try:
        from app.core.pipeline import generate_material_order_pipeline
        await generate_material_order_pipeline(job_id, payload.supplier_name, payload.delivery_date)
        bg_tasks.add_task(backup_database)
        return {"status": "success"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("material_order_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to process material order")"""
        
    office_routes_path.write_text(office_routes_code.replace(old_material_order, new_material_order))

if __name__ == "__main__":
    main()
