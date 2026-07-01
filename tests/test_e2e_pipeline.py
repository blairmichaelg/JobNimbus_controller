import pytest
import asyncio
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_connection

client = TestClient(app)
client.headers.update({"X-Internal-Token": "dev-secret-token"})

@pytest.fixture(autouse=True)
def setup_teardown():
    # Setup - handled by the app lifespan usually, but we ensure tables exist
    yield
    # Cleanup after tests could be added here

def test_full_job_lifecycle(tmp_path):
    """
    E2E integration test that simulates:
    1. A new lead coming in from the field (POST /api/field/jobs)
    2. Verification of LEAD_CAPTURED state
    3. Triggering the master pipeline (POST /api/office/jobs/{id}/eagleview)
    4. Verifying QBO generation with pricing
    5. Verifying INVOICED final state
    """
    
    # 1. Simulate new lead
    lead_payload = {
        "homeowner_name": "E2E Test User",
        "address_line1": "123 Pipeline Blvd",
        "city": "Atlanta",
        "state": "GA",
        "postal_code": "30303",
        "phone": "555-000-1111"
    }
    
    # We bypass ngrok header requirement in testing if we mock it, or just send it
    response = client.post("/api/field/jobs", json=lead_payload, headers={"ngrok-skip-browser-warning": "1"})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    
    # 2. Verify state is LEAD_CAPTURED
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["status"] == "LEAD_CAPTURED"
    finally:
        conn.close()
        
    # 3. Create a fake EV PDF
    fake_pdf = tmp_path / "fake_eagleview.pdf"
    fake_pdf.write_bytes(b"dummy pdf content")
    
    # Mock the extract_eagleview_data so we don't need a real PDF
    # We will use dependency injection or patching for the extraction
    from unittest.mock import patch
    from app.core.supplement_models import EagleViewData
    
    mock_ev_data = EagleViewData(
        total_area_sf=3500.0,
        rake_lf=150.0,
        valley_lf=45.0,
        ridge_lf=120.0,
        hip_lf=0.0,
        eaves_lf=200.0,
        drip_edge_lf=350.0,
        flashing_lf=0.0,
        step_flashing_lf=0.0,
        total_facets=10,
        predominant_pitch="6/12"
    )
    
    with patch("app.core.pipeline.extract_eagleview_data", return_value=mock_ev_data):
        with open(fake_pdf, "rb") as f:
            upload_resp = client.post(
                f"/api/office/jobs/{job_id}/eagleview",
                files={"file": ("fake_eagleview.pdf", f, "application/pdf")}
            )
            
    assert upload_resp.status_code == 200
    resp_data = upload_resp.json()
    assert resp_data["status"] == "success"
    
    # 4. Verify QBO generated with Pricing
    qbo_path = Path(resp_data["pipeline_result"]["qbo_csv_path"])
    assert qbo_path.exists()
    
    # Check pricing in the CSV
    content = qbo_path.read_text(encoding="utf-8")
    # Ensure we actually inserted priced amounts
    assert "12390.00" in content # Field Shingle Bundles
    assert "180.00" in content   # Starter Bundles
    
    # 5. Verify final state is INVOICED
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        assert row["status"] == "INVOICED"
    finally:
        conn.close()
