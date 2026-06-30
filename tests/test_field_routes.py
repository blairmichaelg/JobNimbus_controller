"""
Unit tests for the Field UX FastApi endpoints (Epic 2).
"""

import io
import base64
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.api.field_routes import FIELD_PHOTOS_DIR, SIGNED_AGREEMENTS_DIR
from app.core.cache import set_cached_analysis, init_db
from app.core.inspection_models import PhotoAnalysis, DamageType, Severity

client = TestClient(app)

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
    """POST /api/field/sign should decode base64 and save to disk."""
    # Create a tiny 1x1 base64 transparent PNG
    tiny_png_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    data_uri = f"data:image/png;base64,{tiny_png_base64}"
    
    response = client.post(
        "/api/field/sign",
        json={"job_id": "TEST-SIG-003", "signature_base64": data_uri}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    
    import app.api.field_routes as fr
    expected_path = fr.SIGNED_AGREEMENTS_DIR / "TEST-SIG-003_signature.png"
    assert expected_path.exists()
    
    # Decode and verify physical file bytes
    file_bytes = expected_path.read_bytes()
    assert file_bytes == base64.b64decode(tiny_png_base64)


def test_capture_signature_bad_payload():
    """Invalid base64 should return a 400 error."""
    response = client.post(
        "/api/field/sign",
        json={"job_id": "TEST-SIG-004", "signature_base64": "not_base64!@#"}
    )
    assert response.status_code == 400
