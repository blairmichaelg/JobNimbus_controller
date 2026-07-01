"""
Unit tests for the Office Control Center API routes.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
client.headers.update({"X-Internal-Token": "dev-secret-token"})


class TestOfficeJobsRoute:
    """Tests for GET /api/office/jobs."""

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
