import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import uuid
import sqlite3
import asyncio
from pathlib import Path

from app.main import app
from app.core.database import get_connection, atomic_qbo_export, JobStatus
from app.workers.supplement_processor import process_supplement_event

client = TestClient(app)
response = client.post("/auth/login", data={"pin": "9999", "redirect_url": "/"}, follow_redirects=False)
auth_cookie = response.cookies.get("auth_token")
client.cookies.set("auth_token", auth_cookie)

@pytest.fixture
def db_conn():
    conn = get_connection()
    yield conn
    conn.close()

def setup_test_job(conn: sqlite3.Connection, status: str = "SUPPLEMENT_GENERATED") -> str:
    job_id = str(uuid.uuid4())
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """
        INSERT INTO jobs (id, homeowner_name, address_line1, city, state, postal_code, phone, status)
        VALUES (?, 'Test User', '123 Test St', 'Testville', 'TS', '12345', '555-5555', ?)
        """,
        (job_id, status)
    )
    conn.execute("COMMIT")
    return job_id

def setup_test_financials(conn: sqlite3.Connection, job_id: str, carrier_rcv: float = 0.0, qbo_exported: int = 0):
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """
        INSERT INTO financials (job_id, revenue, carrier_rcv, material_cost, labor_cost, overhead_pct, canvasser_commission_pct, permits_fee, qbo_exported)
        VALUES (?, 1000, ?, 100, 100, 10, 0, 0, ?)
        """,
        (job_id, carrier_rcv, qbo_exported)
    )
    conn.execute("COMMIT")

@pytest.mark.asyncio
@patch('app.core.pipeline.PDFGenerator.generate_supplement_pdf')
@patch('app.core.pipeline.extract_eagleview_data')
@patch('app.services.document_parser.parse_statement_of_loss')
@patch('app.core.pipeline.reconcile')
@patch('app.core.pipeline.parse_code_files')
@patch('app.core.pipeline.get_relevant_codes')
@patch('app.core.pipeline.AIService.generate_supplement_narrative')
@patch('app.core.pipeline.generate_and_gate_flags')
async def test_supplement_pdf_not_deleted_after_vault(
    mock_gate, mock_narrative, mock_get_codes, mock_parse_codes, mock_reconcile, mock_parse_sol, mock_ev, mock_gen_pdf, db_conn, tmp_path
):
    job_id = setup_test_job(db_conn, "EV_PARSED")
    
    mock_gen_pdf.return_value = str(tmp_path / "temp_mock.pdf")
    # Actually create the temp mock file
    with open(str(tmp_path / "temp_mock.pdf"), "w") as f:
        f.write("mock pdf content")
        
    from app.core.supplement_models import EagleViewData
    ev_data = EagleViewData(
        total_area_sf=1000.0, rake_lf=0, valley_lf=20.0, ridge_lf=0, hip_lf=0,
        eaves_lf=50.0, drip_edge_lf=0, flashing_lf=0, step_flashing_lf=0,
        total_facets=2, predominant_pitch="6/12"
    )
    mock_ev.return_value = (ev_data, "hash")
    mock_parse_sol.return_value = MagicMock(line_items=[])
    
    # Also mock financials so it doesn't fail Fix 2
    mock_sol = MagicMock(line_items=[])
    mock_sol.financials.gross_rcv.verified = True
    mock_parse_sol.return_value = mock_sol
    mock_reconcile.return_value = MagicMock(model_dump_json=lambda: "{}")
    mock_parse_codes.return_value = None
    mock_get_codes.return_value = ""
    mock_narrative.return_value = "narrative"
    mock_gate.return_value = False

    result = await process_supplement_event(
        ctx={}, job_id=job_id, ev_pdf_path="dummy", sol_pdf_path="dummy", ev_sha256="dummy", ev_doc_id="dummy", sol_sha256="dummy", sol_doc_id="dummy"
    )

    assert result["status"] == "success"
    
    # Check that temp file no longer exists
    assert not (tmp_path / "temp_mock.pdf").exists()
    
    # Check that permanent file exists
    vault_path = Path("data/field_docs") / job_id / "Supplement_Request.pdf"
    assert vault_path.exists()
    
    # Clean up
    vault_path.unlink()

def test_accounting_brief_rcv_is_live_not_mock(db_conn):
    job_id = setup_test_job(db_conn, "SUPPLEMENT_GENERATED")
    setup_test_financials(db_conn, job_id, carrier_rcv=5000.0)

    response = client.get("/api/office/accounting/brief")
    assert response.status_code == 200
    data = response.json()
    assert data["supplemented_rcv_added"] == "$5,000.00"

@pytest.mark.asyncio
async def test_atomic_qbo_export_prevents_double_export(db_conn):
    job1 = setup_test_job(db_conn, "INVOICED")
    job2 = setup_test_job(db_conn, "SUPPLEMENT_APPROVED")
    setup_test_financials(db_conn, job1)
    setup_test_financials(db_conn, job2)

    async def call_atomic():
        return await asyncio.to_thread(atomic_qbo_export)

    # Run two concurrently
    results = await asyncio.gather(call_atomic(), call_atomic())
    
    # Only one of the calls should have successfully returned the 2 rows. 
    # The other call should return 0 rows.
    batch1, batch2 = results
    
    total_returned = len(batch1) + len(batch2)
    assert total_returned == 2
    
    cursor = db_conn.execute("SELECT qbo_exported FROM financials WHERE job_id IN (?, ?)", (job1, job2))
    rows = cursor.fetchall()
    for row in rows:
        assert row["qbo_exported"] == 1

def test_download_export_path_traversal_blocked():
    response = client.get("/api/office/download/.env")
    assert response.status_code == 400

@pytest.mark.asyncio
async def test_resume_fails_gracefully_without_saved_report(db_conn):
    job_id = setup_test_job(db_conn, "PENDING_OPERATOR_REVIEW")
    
    result = await process_supplement_event(
        ctx={}, job_id=job_id, ev_pdf_path="dummy", sol_pdf_path="dummy", ev_sha256="dummy", ev_doc_id="dummy", sol_sha256="dummy", sol_doc_id="dummy", resume=True
    )
    
    assert result == {"status": "failed", "reason": "no_saved_report"}
    
    cursor = db_conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
    status = cursor.fetchone()["status"]
    assert status == JobStatus.PIPELINE_FAILED.value
