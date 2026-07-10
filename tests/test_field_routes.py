"""
Unit tests for the Field UX FastApi endpoints (Epic 2).
"""

import io
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.cache import set_cached_analysis, init_db
from app.core.inspection_models import PhotoAnalysis, DamageType, Severity

client = TestClient(app)
client.headers.update({"X-Internal-Token": "field-secret-token"})

@pytest.fixture(autouse=True)
def setup_dirs(tmp_path, monkeypatch):
    """Point directories to a temp path during tests to avoid littering the repo."""
    test_field_photos = tmp_path / "field_photos"
    test_field_docs = tmp_path / "field_docs"
    test_signed = tmp_path / "signed_agreements"
    
    test_field_photos.mkdir()
    test_field_docs.mkdir()
    test_signed.mkdir()
    
    monkeypatch.setattr("app.api.field_routes.FIELD_PHOTOS_DIR", test_field_photos)
    monkeypatch.setattr("app.api.field_routes.FIELD_DOCS_DIR", test_field_docs)
    monkeypatch.setattr("app.api.field_routes.SIGNED_AGREEMENTS_DIR", test_signed)
    
    # Ensure cache and CRM DB exists for the test
    init_db()
    from app.core.database import init_db as init_crm_db
    init_crm_db()
    
    yield
    
    # Cleanup handled by tmp_path

def test_field_routes_deny_office_token():
    """Should return 401 Unauthorized if using an office token."""
    response = client.get("/api/field/jobs/TEST-123/inspection", headers={"X-Internal-Token": "office-secret-token"})
    assert response.status_code == 401
    assert "Invalid internal token" in response.json()["detail"]

def test_create_new_job_lead_intake():
    """POST /api/field/jobs should insert a DB row and create directories."""
    payload = {
        "homeowner_name": "Alice Smith",
        "address_line1": "123 Test Ave",
        "city": "Atlanta",
        "state": "GA",
        "postal_code": "30301",
        "phone": "555-0100"
    }
    response = client.post("/api/field/jobs", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "job_id" in data
    
    job_id = data["job_id"]
    
    # Verify directories were created
    import app.api.field_routes as fr
    assert (fr.FIELD_PHOTOS_DIR / job_id).exists()
    assert (fr.FIELD_DOCS_DIR / job_id).exists()
    
    # Verify SQLite DB
    from app.core.database import get_connection
    conn = get_connection()
    cursor = conn.execute("SELECT homeowner_name, status, status_history FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row["homeowner_name"] == "Alice Smith"
    assert row["status"] == "LEAD_CAPTURED"
    assert "Initial canvasser intake via Truck Server" in row["status_history"]


def test_upload_field_photo():
    """POST /api/field/jobs/{id}/photos should save the photo."""
    file_content = b"fake_jpeg_content"
    
    response = client.post(
        "/api/field/jobs/TEST-JOB-001/photos",
        files={"file": ("test_roof.jpg", file_content, "image/jpeg")}
    )
    
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["filename"] == "test_roof.jpg"
    
    # Verify file was physically written to the mocked FIELD_PHOTOS_DIR
    import app.api.field_routes as fr
    saved_file = fr.FIELD_PHOTOS_DIR / "TEST-JOB-001" / "test_roof.jpg"
    assert saved_file.exists()
    assert saved_file.read_bytes() == file_content


def test_upload_missing_file():
    """Missing file payload should be rejected by FastAPI directly."""
    response = client.post("/api/field/jobs/TEST-JOB-001/photos")
    assert response.status_code == 422  # Unprocessable Entity


def test_get_inspection_summary():
    """GET /api/field/jobs/{id}/inspection should aggregate photos and cache."""
    # 1. Provide a physical file for get_stable_photos
    import app.api.field_routes as fr
    job_dir = fr.FIELD_PHOTOS_DIR / "TEST-JOB-002"
    job_dir.mkdir()
    photo_path = job_dir / "valid_image.jpg"
    photo_path.write_bytes(b"\xff\xd8" + b"A" * 100)  # valid-ish jpeg content
    
    # 2. Inject an analysis into the SQLite cache
    analysis = PhotoAnalysis(
        filename="valid_image.jpg",
        damage_detected=True,
        damage_type=DamageType.HAIL,
        severity=Severity.MODERATE,
        confidence=0.99,
        forensic_narrative="Test"
    )
    set_cached_analysis("TEST-JOB-002", "fake_hash", analysis)
    
    # 3. Call the endpoint
    response = client.get("/api/field/jobs/TEST-JOB-002/inspection")
    
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "TEST-JOB-002"
    
    # Check that photos and analyses were populated
    assert len(data["photos"]) == 1
    assert data["photos"][0]["filepath"].endswith("valid_image.jpg")
    
    assert len(data["analyses"]) == 1
    assert data["analyses"][0]["filename"] == "valid_image.jpg"
    assert data["analyses"][0]["damage_detected"] is True


def test_capture_signature():
    """POST /api/field/jobs/{job_id}/contingency-sign should decode base64, save PNG, and generate PDF."""
    from app.core.database import get_connection
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, homeowner_name, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("99999999-9999-9999-9999-999999999993", "Test Homeowner", "123 Test St", "City", "State", "00000", "555-5555")
    )
    conn.commit()
    conn.close()

    tiny_png_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    data_uri = f"data:image/png;base64,{tiny_png_base64}"
    
    response = client.post(
        "/api/field/jobs/99999999-9999-9999-9999-999999999993/contingency-sign",
        json={
            "signature_base64": data_uri,
            "signer_name": "Test Homeowner",
            "ip_address": "127.0.0.1",
            "user_agent": "Pytest"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "pdf_path" in data
    
    import app.api.field_routes as fr
    expected_path = fr.SIGNED_AGREEMENTS_DIR / "99999999-9999-9999-9999-999999999993_contingency_sig.png"
    assert expected_path.exists()
    
    from PIL import Image
    file_bytes = expected_path.read_bytes()
    # Verify the saved image is valid
    saved_img = Image.open(io.BytesIO(file_bytes))
    saved_img.verify()
    assert saved_img.format == "PNG"


def test_capture_signature_bad_payload():
    """Invalid base64 should return a 400 error due to PDF/Image failure."""
    from app.core.database import get_connection
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, homeowner_name, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("99999999-9999-9999-9999-999999999994", "Test Homeowner", "123 Test St", "City", "State", "00000", "555-5555")
    )
    conn.commit()
    conn.close()
    
    response = client.post(
        "/api/field/jobs/99999999-9999-9999-9999-999999999994/contingency-sign",
        json={
            "signature_base64": "data:image/png;base64,not_base64!@#",
            "signer_name": "Test Homeowner"
        }
    )
    assert response.status_code == 400
    assert "Invalid or corrupt image data" in response.json()["detail"]

def test_capture_signature_payload_too_large():
    """Payload > 2MB should return 413."""
    large_payload = "data:image/png;base64," + ("A" * 2_000_001)
    response = client.post(
        "/api/field/jobs/99999999-9999-9999-9999-999999999994/contingency-sign",
        json={
            "signature_base64": large_payload,
            "signer_name": "Test Homeowner"
        }
    )
    assert response.status_code == 413
    assert "Payload too large" in response.json()["detail"]


def test_resolve_flag_success():
    """Test that a flag is successfully updated and resolved."""
    from app.core.database import get_connection
    import uuid
    conn = get_connection()
    job_id = str(uuid.uuid4())
    flag_id = str(uuid.uuid4())
    rule_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, homeowner_name, address_line1, city, state, postal_code, phone) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (job_id, "Test Homeowner", "123 Test St", "City", "State", "00000", "555-5555")
    )
    conn.execute("INSERT INTO supplement_rules (id, parent_code, required_child_code, citation_text, citation_type, trigger_logic_name, climate_dependent) VALUES (?, 'RFG', 'RFG IWS', 'Fake Rule', 'IRC', 'calc', 1)", (rule_id,))
    conn.execute("INSERT INTO supplement_flags (id, job_id, rule_id, triggered, quantity_delta, notes) VALUES (?, ?, ?, 1, 0.0, 'MANUAL REVIEW REQUIRED: Error')", (flag_id, job_id, rule_id))
    conn.commit()
    conn.close()
    
    response = client.patch(
        f"/api/field/jobs/{job_id}/flags/{flag_id}",
        json={
            "quantity_delta": 5.5,
            "resolution_note": "Found the right measurement"
        }
    )
    assert response.status_code == 200
    
    conn = get_connection()
    cursor = conn.execute("SELECT quantity_delta, notes FROM supplement_flags WHERE id = ?", (flag_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row["quantity_delta"] == 5.5
    assert row["notes"] == "RESOLVED: Found the right measurement"

def test_resolve_flag_invalid_uuid():
    """Test path traversal defense."""
    response = client.patch(
        "/api/field/jobs/invalid-job/flags/123",
        json={"quantity_delta": 1.0, "resolution_note": "test"}
    )
    assert response.status_code == 400
