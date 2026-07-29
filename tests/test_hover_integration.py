import os
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import get_connection
from app.api.auth import create_access_token

client = TestClient(app)

def test_eagleview_upload_endpoint_hover_file(setup_test_db):
    conn = get_connection()
    conn.execute("INSERT INTO jobs (id, homeowner_name, status, job_type, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                 ("hover-integration-job", "Hover Test", "LEAD", "INSURANCE", "123", "City", "ST", "123", "123"))
    conn.commit()
    conn.close()

    pdf_path = r"C:\Users\Michael\Downloads\182148217298587.pdf"
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
    assert data["pipeline_result"]["ev_data"]["total_area_sf"] == 2512.0

def test_eagleview_upload_endpoint_unknown_file(setup_test_db):
    conn = get_connection()
    conn.execute("INSERT INTO jobs (id, homeowner_name, status, job_type, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                 ("hover-unknown-job", "Unknown Test", "LEAD", "INSURANCE", "123", "City", "ST", "123", "123"))
    conn.commit()
    conn.close()

    dummy_path = "dummy_unknown.pdf"
    with open(dummy_path, "wb") as f:
        f.write(b"%PDF-1.4 dummy non-hover non-eagleview content")
        
    admin_token = create_access_token(role="admin")
    
    try:
        with open(dummy_path, "rb") as f:
            files = {"file": ("dummy.pdf", f, "application/pdf")}
            response = client.post(
                "/api/office/jobs/hover-unknown-job/eagleview",
                files=files,
                cookies={"auth_token": admin_token}
            )

        assert response.status_code == 400
        assert "Unknown measurement PDF format" in response.json()["detail"]
    finally:
        if os.path.exists(dummy_path):
            os.remove(dummy_path)
