import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import uuid
import sqlite3
from app.main import app
from app.core.database import update_material_flags, JobStatus, get_qbo_export_batch, mark_qbo_exported, get_connection
from app.config import get_settings

client = TestClient(app)

# Bypass background tasks for testing
@pytest.fixture(autouse=True)
def mock_background_tasks(monkeypatch):
    monkeypatch.setattr("app.api.office_routes.BackgroundTasks.add_task", MagicMock())

@pytest.fixture
def auth_headers():
    settings = get_settings()
    return {"x-internal-token": settings.INTERNAL_API_TOKEN}

@pytest.fixture
def db_conn():
    conn = get_connection()
    yield conn
    conn.close()

def setup_test_job(conn: sqlite3.Connection, status: str = "MATERIAL_ORDERED") -> str:
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

def setup_test_financials(conn: sqlite3.Connection, job_id: str, qbo_exported: int = 0):
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """
        INSERT INTO financials (job_id, revenue, carrier_rcv, material_cost, labor_cost, overhead_pct, canvasser_commission_pct, permits_fee, qbo_exported)
        VALUES (?, 1000, 1000, 100, 100, 10, 0, 0, ?)
        """,
        (job_id, qbo_exported)
    )
    conn.execute("COMMIT")

def test_material_flag_patch_requires_valid_uuid(auth_headers):
    response = client.patch(
        "/api/operations/job/not-a-uuid/materials",
        headers=auth_headers,
        json={"materials_ordered": True}
    )
    assert response.status_code == 400
    assert "Invalid job_id format" in response.json()["detail"]

def test_material_flag_patch_missing_both_flags(auth_headers):
    job_id = str(uuid.uuid4())
    response = client.patch(
        f"/api/operations/job/{job_id}/materials",
        headers=auth_headers,
        json={}
    )
    assert response.status_code == 422
    assert "Provide at least one flag" in response.json()["detail"]

def test_material_flag_on_site_drives_state_machine(db_conn):
    job_id = setup_test_job(db_conn, "MATERIAL_ORDERED")
    
    update_material_flags(job_id, materials_on_site=True)
    
    cursor = db_conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    assert row["status"] == JobStatus.MATERIALS_ON_SITE.value

def test_qbo_export_batch_excludes_already_exported(db_conn):
    job1_id = setup_test_job(db_conn, "INVOICED")
    job2_id = setup_test_job(db_conn, "INVOICED")
    
    setup_test_financials(db_conn, job1_id, qbo_exported=0)
    setup_test_financials(db_conn, job2_id, qbo_exported=1)
    
    batch = get_qbo_export_batch()
    
    job_ids = [r["job_id"] for r in batch]
    assert job1_id in job_ids
    assert job2_id not in job_ids

def test_qbo_mark_exported_idempotent(db_conn):
    job_id = setup_test_job(db_conn, "INVOICED")
    setup_test_financials(db_conn, job_id, qbo_exported=0)
    
    # Call mark twice
    mark_qbo_exported([job_id])
    mark_qbo_exported([job_id])
    
    cursor = db_conn.execute("SELECT qbo_exported FROM financials WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    assert row["qbo_exported"] == 1
