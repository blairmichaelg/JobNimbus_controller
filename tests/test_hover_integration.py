import os
import tempfile
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import get_connection
from app.api.auth import create_access_token

client = TestClient(app)


def test_eagleview_upload_endpoint_hover_file(setup_test_db):
    """Test upload endpoint with a Hover-format PDF.
    
    NOTE: This test requires a real Hover PDF file. It is skipped if
    the file is not available, which is the expected behaviour in CI.
    To run this locally, set HOVER_TEST_PDF to the path of a real
    Hover measurement PDF.
    """
    pdf_path = os.environ.get("HOVER_TEST_PDF")
    if not pdf_path or not os.path.exists(pdf_path):
        import pytest
        pytest.skip("HOVER_TEST_PDF not set or file not found — skipping live Hover integration test")
    
    conn = get_connection()
    conn.execute("INSERT INTO jobs (id, homeowner_name, status, job_type, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                 ("hover-integration-job", "Hover Test", "LEAD", "INSURANCE", "123", "City", "ST", "123", "123"))
    conn.commit()
    conn.close()

    admin_token = create_access_token(role="admin")
    
    with open(pdf_path, "rb") as f:
        files = {"file": ("hover_report.pdf", f, "application/pdf")}
        response = client.post(
            "/api/office/jobs/hover-integration-job/eagleview",
            files=files,
            cookies={"auth_token": admin_token}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


def test_eagleview_upload_endpoint_unknown_file(setup_test_db):
    conn = get_connection()
    conn.execute("INSERT INTO jobs (id, homeowner_name, status, job_type, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                 ("hover-unknown-job", "Unknown Test", "LEAD", "INSURANCE", "123", "City", "ST", "123", "123"))
    conn.commit()
    conn.close()

    admin_token = create_access_token(role="admin")
    
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(b"%PDF-1.4 dummy non-hover non-eagleview content")
        tmp_path = tmp.name
    
    try:
        with open(tmp_path, "rb") as f:
            files = {"file": ("dummy.pdf", f, "application/pdf")}
            response = client.post(
                "/api/office/jobs/hover-unknown-job/eagleview",
                files=files,
                cookies={"auth_token": admin_token}
            )

        assert response.status_code == 400
        assert "Unknown measurement PDF format" in response.json()["detail"]
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
