"""
Unit tests for the V4 SQLite Database interactions.
"""

import pytest
import sqlite3
import json
from unittest.mock import patch, MagicMock

from app.core.database import update_job_status, JobStatus, init_db

def test_update_job_status_valid_enum():
    """Test that a valid enum string passes validation."""
    with patch("app.core.database.get_connection") as mock_get_conn:
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        
        # Mock cursor for SELECT
        mock_cursor = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"status_history": json.dumps([])}
        
        # Should not raise ValueError
        update_job_status("job_123", "INVOICED", "Test note")
        
        # Verify the UPDATE was called
        assert mock_conn.execute.call_count == 2
        mock_conn.commit.assert_called_once()

def test_update_job_status_invalid_string_raises_value_error():
    """Test that arbitrary strings raise a ValueError to prevent bad data."""
    with patch("app.core.database.get_connection") as mock_get_conn:
        with pytest.raises(ValueError, match="Invalid job status: INVALID_STATUS"):
            update_job_status("job_123", "INVALID_STATUS", "This should fail")
            
        # Verify connection was never opened due to early validation
        mock_get_conn.assert_not_called()

def test_update_job_status_missing_job_raises_value_error():
    """Test that a missing job raises a ValueError."""
    with patch("app.core.database.get_connection") as mock_get_conn:
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        
        # Mock cursor for SELECT returning None
        mock_cursor = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        
        with pytest.raises(ValueError, match="Job job_missing not found."):
            update_job_status("job_missing", "INVOICED", "Test note")
