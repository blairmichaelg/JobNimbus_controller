import os
from pathlib import Path

def main():
    root = Path("c:/Users/Michael/projects/JobNimbus_controller")
    pipeline_path = root / "app" / "core" / "pipeline.py"
    
    # --- Rebuttal Processor ---
    rebuttal_processor_path = root / "app" / "workers" / "rebuttal_processor.py"
    rebuttal_code = rebuttal_processor_path.read_text()
    rebuttal_logic = rebuttal_code.replace('async def process_rebuttal(\n    ctx: dict,\n    job_id: str,\n    denial_text: str | None = None,\n    denial_pdf_doc_id: str | None = None\n) -> dict:', 'async def run_rebuttal_pipeline(\n    job_id: str,\n    denial_text: str | None = None,\n    denial_pdf_doc_id: str | None = None\n) -> dict:')
    rebuttal_logic = rebuttal_logic.replace('logger = structlog.get_logger("app.workers.rebuttal_processor")', '')
    rebuttal_logic = rebuttal_logic.replace('import asyncio\nimport structlog\nfrom app.core.database import (\n    get_connection, update_job_status, insert_job_document,\n    JobStatus\n)\nfrom app.services.ai_service import AIService\nfrom app.services.pdf_generator import PDFGenerator', '')
    
    with open(pipeline_path, "a") as f:
        f.write('\nfrom app.services.ai_service import AIService\n')
        f.write(rebuttal_logic.replace('"""\nARQ Worker: Rebuttal Letter Generator', '"""\nRebuttal Letter Generator Pipeline'))
    
    rebuttal_processor_path.write_text('''"""
ARQ Worker: Rebuttal Letter Generator
"""

import structlog
from app.core.pipeline import run_rebuttal_pipeline

logger = structlog.get_logger("app.workers.rebuttal_processor")

async def process_rebuttal(
    ctx: dict,
    job_id: str,
    denial_text: str | None = None,
    denial_pdf_doc_id: str | None = None
) -> dict:
    return await run_rebuttal_pipeline(job_id, denial_text, denial_pdf_doc_id)
''')

    # --- Supplement Processor ---
    supplement_processor_path = root / "app" / "workers" / "supplement_processor.py"
    supplement_code = supplement_processor_path.read_text()
    
    supplement_logic = supplement_code.replace('async def process_supplement_event(\n    ctx: dict,\n    job_id: str,\n    ev_pdf_path: str,\n    sol_pdf_path: str,\n    ev_sha256: str,\n    ev_doc_id: str,\n    sol_sha256: str,\n    sol_doc_id: str,\n) -> dict:', 'async def run_supplement_pipeline(\n    job_id: str,\n    ev_pdf_path: str,\n    sol_pdf_path: str,\n    ev_sha256: str,\n    ev_doc_id: str,\n    sol_sha256: str,\n    sol_doc_id: str,\n) -> dict:')
    supplement_logic = supplement_logic.replace('logger = structlog.get_logger("app.workers.supplement_processor")', '')
    
    # Find the imports to strip out
    import_block = """import asyncio
import structlog
from pathlib import Path
from pydantic import ValidationError

from app.core.database import (
    update_job_status, JobStatus, insert_supplement_report, get_connection
)
from app.services.pdf_extractor import extract_eagleview_data
from app.services.ai_service import AIService
from app.core.reconciliation import reconcile
from app.services.pdf_generator import PDFGenerator"""
    supplement_logic = supplement_logic.replace(import_block, '')
    
    with open(pipeline_path, "a") as f:
        f.write('\nfrom pydantic import ValidationError\nfrom app.core.database import insert_supplement_report\n')
        f.write(supplement_logic.replace('"""\nARQ Worker: Supplement Pipeline orchestrator.', '"""\nSupplement Pipeline orchestrator.'))
    
    supplement_processor_path.write_text('''"""
ARQ Worker: Supplement Pipeline orchestrator.
"""

import structlog
from app.core.pipeline import run_supplement_pipeline

logger = structlog.get_logger("app.workers.supplement_processor")

async def process_supplement_event(
    ctx: dict,
    job_id: str,
    ev_pdf_path: str,
    sol_pdf_path: str,
    ev_sha256: str,
    ev_doc_id: str,
    sol_sha256: str,
    sol_doc_id: str,
) -> dict:
    return await run_supplement_pipeline(
        job_id, ev_pdf_path, sol_pdf_path, ev_sha256, ev_doc_id, sol_sha256, sol_doc_id
    )
''')

    # --- Test Worker Settings ---
    test_path = root / "tests" / "test_worker_settings.py"
    test_path.write_text('''import pytest
import importlib

from app.workers.settings import WorkerSettings

def test_worker_settings_functions_resolvable():
    for func_path in WorkerSettings.functions:
        module_path, func_name = func_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        assert callable(func), f"{func_path} is not callable"
''')

if __name__ == "__main__":
    main()
