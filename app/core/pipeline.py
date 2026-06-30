import structlog
from pathlib import Path

from app.services.pdf_extractor import extract_eagleview_data
from app.core.reconciliation import reconcile
from app.core.supplement_models import StatementOfLoss
from app.services.qbo_export import generate_qbo_invoice
from app.core.database import update_job_status, JobStatus

logger = structlog.get_logger("app.core.pipeline")

def run_full_office_pipeline(job_id: str, ev_pdf_path: Path, customer_name: str = "Unknown Customer") -> dict:
    """
    The Master Orchestrator for the V4 Pipeline.
    Strictly executes the chain: Parse EV PDF -> Calculate BOM -> Generate QBO CSV -> Transition Status.
    """
    log = logger.bind(job_id=job_id)
    log.info("master_pipeline_started", ev_pdf_path=str(ev_pdf_path))
    
    try:
        # 1. Parse EV PDF
        import asyncio
        ev_data = asyncio.run(extract_eagleview_data(ev_pdf_path))
        log.info("pipeline_ev_parsed", sq=ev_data.total_area_sf / 100.0)
        
        # 2. Calculate BOM
        from app.core.complexity import compute_complexity_score, calculate_dynamic_waste
        score = compute_complexity_score(ev_data)
        waste = calculate_dynamic_waste(score)
        empty_sol = StatementOfLoss(line_items=[], overhead_and_profit_included=True)
        report = reconcile(ev_data, empty_sol, job_id, waste_factor=waste)
        bom = report.material_bom
        log.info("pipeline_bom_calculated", field_bundles=bom.field_shingle_bundles)
        
        # 3. Generate QBO CSV with dynamic pricing
        csv_path = generate_qbo_invoice(job_id, bom, customer_name=customer_name)
        log.info("pipeline_qbo_generated", csv_path=csv_path)
        
        # 4. Transition Status
        update_job_status(job_id, JobStatus.INVOICED, f"Automated Pipeline Completed. QBO Invoice: {Path(csv_path).name}")
        log.info("master_pipeline_completed")
        
        return {
            "status": "success",
            "ev_data": ev_data.model_dump(),
            "bom": bom.model_dump(),
            "qbo_csv_path": csv_path
        }
        
    except Exception as e:
        log.error("master_pipeline_failed", error=str(e))
        raise
