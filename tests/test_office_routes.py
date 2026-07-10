"""
Unit tests for the Office Control Center API routes.
"""

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
client.headers.update({"X-Internal-Token": "office-secret-token"})


class TestOfficeJobsRoute:
    """Tests for GET /api/office/jobs."""

    def test_office_routes_deny_field_token(self):
        """Should return 401 Unauthorized if using a field token."""
        response = client.get("/api/office/jobs", headers={"X-Internal-Token": "field-secret-token"})
        assert response.status_code == 401
        assert "Invalid internal token" in response.json()["detail"]

    @patch("app.api.office_routes.get_connection")
    def test_get_jobs_success(self, mock_get_connection):
        """Should return jobs properly parsed from SQLite."""
        
        # Mock the SQLite cursor and rows
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        
        # We simulate the sqlite3.Row behavior using a dict
        mock_cursor.fetchall.return_value = [
            {
                "id": "job-123",
                "homeowner_name": "John Doe",
                "address_line1": "123 Main St",
                "city": "Atlanta",
                "state": "GA",
                "postal_code": "30301",
                "phone": "555-0100",
                "email": "john@example.com",
                "claim_number": "CLM-999",
                "insurer_name": "State Farm",
                "status": "PHOTOS_UPLOADED",
                "status_history": '[{"status": "LEAD_CAPTURED", "timestamp": "2026-06-30T10:00:00Z"}]',
                "created_at": "2026-06-30 10:00:00"
            }
        ]
        
        mock_get_connection.return_value = mock_conn

        response = client.get("/api/office/jobs")
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data) == 1
        job = data[0]
        assert job["id"] == "job-123"
        assert job["homeowner_name"] == "John Doe"
        # Verify JSON decoding
        assert len(job["status_history"]) == 1
        assert job["status_history"][0]["status"] == "LEAD_CAPTURED"
        
        mock_conn.close.assert_called_once()

    @patch("app.api.office_routes.get_connection")
    def test_get_jobs_db_error(self, mock_get_connection):
        """Should return 500 if database query fails."""
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("Database locked")
        mock_get_connection.return_value = mock_conn

        response = client.get("/api/office/jobs")
        
        assert response.status_code == 500
        assert "Failed to fetch jobs" in response.json()["detail"]
        
        mock_conn.close.assert_called_once()


class TestOfficeFinancialsRoute:
    @patch("app.api.office_routes.compute_job_profitability")
    @patch("app.api.office_routes.upsert_financials")
    @patch("app.api.office_routes.backup_database")
    def test_update_financials_background_backup(self, mock_backup, mock_upsert, mock_compute):
        """Verifies that backup_database is delegated to BackgroundTasks and executed."""
        mock_compute.return_value = {"gross_margin": 0.40, "direct_costs": 5000}
        
        payload = {
            "revenue": 10000,
            "carrier_rcv": 10000,
            "materials": 3000,
            "labor": 2000,
            "overhead_pct": 0.25,
            "commission_pct": 0.10,
            "permits_fee": 0
        }
        
        response = client.post("/api/office/jobs/job-123/financials", json=payload)
        
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        
        # In FastAPI TestClient, background tasks are executed synchronously after response
        mock_backup.assert_called_once()

class TestUploadIdempotency:
    @patch("app.api.office_routes.stream_upload_safely")
    @patch("app.api.office_routes.get_job_document_by_hash")
    @patch("app.api.office_routes.run_full_office_pipeline")
    def test_upload_eagleview_idempotency(self, mock_run_pipeline, mock_get_doc, mock_stream):
        """Test that identical file uploads are short-circuited."""
        # 1. Simulate upload returning a specific hash
        mock_stream.return_value = "fake_sha256_hash"
        
        # 2. Simulate database already having this hash
        mock_get_doc.return_value = {"id": "doc123", "sha256_hash": "fake_sha256_hash"}
        
        # 3. Simulate file upload
        file_content = b"fake pdf content"
        response = client.post(
            "/api/office/jobs/job-123/eagleview",
            files={"file": ("eagleview.pdf", file_content, "application/pdf")}
        )
        
        # 4. Verify API response
        assert response.status_code == 200
        assert "Duplicate file detected" in response.json()["message"]
        
        # 5. Verify the pipeline was completely bypassed
        mock_run_pipeline.assert_not_called()
