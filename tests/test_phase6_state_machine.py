import pytest
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import (
    get_connection, generate_invoice_id, update_job_status,
    JobStatus
)

client = TestClient(app)

response = client.post("/auth/login", data={"pin": "9999", "redirect_url": "/"}, follow_redirects=False)
office_token = response.cookies.get("auth_token")
client.cookies.set("auth_token", office_token)

response = client.post("/auth/login", data={"pin": "2222", "redirect_url": "/"}, follow_redirects=False)
ops_token = response.cookies.get("auth_token")

response = client.post("/auth/login", data={"pin": "3333", "redirect_url": "/"}, follow_redirects=False)
field_token = response.cookies.get("auth_token")

# Default client cookie to office_token for office routes
client.cookies.set("auth_token", office_token)
@pytest.fixture(autouse=True)
def setup_teardown_db():
    conn = get_connection()
    # Ensure invoice_sequence exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invoice_sequence (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_seq INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("INSERT OR IGNORE INTO invoice_sequence (id, last_seq) VALUES (1, 0)")
    conn.commit()
    conn.close()
    yield
    # No teardown needed, in-memory or test DB is handled by main conftest usually

def test_invoice_id_generation():
    """Test human-readable invoice ID generation (WR-YY-NNNN)."""
    inv1 = generate_invoice_id()
    inv2 = generate_invoice_id()
    assert inv1.startswith("WR-")
    assert inv2.startswith("WR-")
    assert inv1 != inv2
    # Ensure sequence increments
    seq1 = int(inv1.split("-")[2])
    seq2 = int(inv2.split("-")[2])
    assert seq2 == seq1 + 1

def test_state_machine_guard_approve_supplement():
    """Test SUPPLEMENT_APPROVED requires correct prior state."""
    job_id = str(uuid4())
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, homeowner_name, status, status_history, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, "Test", JobStatus.SUPPLEMENT_GENERATED, "[]", "123", "City", "ST", "00000", "555")
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="ILLEGAL TRANSITION: SUPPLEMENT_APPROVED requires"):
        update_job_status(job_id, JobStatus.SUPPLEMENT_APPROVED, "Test")

def test_state_machine_guard_deny_supplement():
    """Test SUPPLEMENT_DENIED requires correct prior state."""
    job_id = str(uuid4())
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, homeowner_name, status, status_history, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, "Test", JobStatus.MATERIAL_ORDERED, "[]", "123", "City", "ST", "00000", "555")
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="ILLEGAL TRANSITION: SUPPLEMENT_DENIED requires"):
        update_job_status(job_id, JobStatus.SUPPLEMENT_DENIED, "Test")

def test_approve_supplement_route():
    """Test API endpoint for supplement approval."""
    job_id = str(uuid4())
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, homeowner_name, status, status_history, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, "Test", JobStatus.AWAITING_CARRIER_RESPONSE, "[]", "123", "City", "ST", "00000", "555")
    )
    conn.commit()
    conn.close()

    response = client.post(f"/api/office/jobs/{job_id}/approve-supplement", json={"note": "Looks good"})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    conn = get_connection()
    status = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()["status"]
    conn.close()
    assert status == JobStatus.SUPPLEMENT_APPROVED

def test_deny_supplement_route_missing_payload():
    """Test API endpoint for supplement denial without text fails."""
    job_id = str(uuid4())
    response = client.post(f"/api/office/jobs/{job_id}/deny-supplement", json={})
    assert response.status_code == 400
    assert "Must provide denial_text" in response.text

def test_deny_supplement_route_success():
    """Test API endpoint for supplement denial triggers worker."""
    job_id = str(uuid4())
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, homeowner_name, status, status_history, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, "Test", JobStatus.AWAITING_CARRIER_RESPONSE, "[]", "123", "City", "ST", "00000", "555")
    )
    conn.commit()
    conn.close()

    class MockPool:
        async def enqueue_job(self, func, **kwargs):
            self.enqueued = func
    
    mock_pool = MockPool()
    app.state.redis_pool = mock_pool

    response = client.post(f"/api/office/jobs/{job_id}/deny-supplement", json={"denial_text": "Not covered"})
    assert response.status_code == 200
    assert response.json()["status"] == "denied_rebuttal_queued"

    conn = get_connection()
    status = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()["status"]
    conn.close()
    assert status == JobStatus.SUPPLEMENT_DENIED

def test_operations_schedule_route():
    """Test API endpoint for assigning a crew."""
    job_id = str(uuid4())
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, homeowner_name, status, status_history, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, "Test", JobStatus.MATERIALS_ON_SITE, "[]", "123", "City", "ST", "00000", "555")
    )
    conn.commit()
    conn.close()

    response = client.post(
        f"/api/operations/jobs/{job_id}/schedule",
        json={"crew_name": "Alpha", "install_date": "2026-08-01"},
        cookies={"auth_token": ops_token}
    )
    assert response.status_code == 200

    conn = get_connection()
    status = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()["status"]
    sched = conn.execute("SELECT crew_name FROM schedule WHERE job_id = ?", (job_id,)).fetchone()["crew_name"]
    conn.close()
    
    assert status == JobStatus.INSTALL_SCHEDULED
    assert sched == "Alpha"

def test_field_routes_retail_job_enqueue():
    """Test job creation triggers retail worker for RETAIL type."""
    class MockPool:
        async def enqueue_job(self, func, **kwargs):
            self.enqueued = func
    
    mock_pool = MockPool()
    app.state.redis_pool = mock_pool

    payload = {
        "homeowner_name": "Retail Bob",
        "address_line1": "123 Retail Ave",
        "city": "Atlanta",
        "state": "GA",
        "postal_code": "30301",
        "phone": "555-0000",
        "email": "bob@retail.com",
        "job_type": "RETAIL"
    }

    response = client.post("/api/field/jobs", json=payload, cookies={"auth_token": field_token})
    assert response.status_code == 200
    assert mock_pool.enqueued == "process_retail_quote"
