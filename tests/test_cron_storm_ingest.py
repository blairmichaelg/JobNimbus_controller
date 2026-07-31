import pytest
from unittest.mock import patch
from scripts.cron_storm_ingest import fetch_storm_data

@patch('scripts.cron_storm_ingest.requests.get')
@patch('scripts.cron_storm_ingest.sqlite3.connect')
def test_storm_ingest(mock_connect, mock_get):
    # Setup mock response from IEM
    mock_resp = mock_get.return_value
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'features': [
            {
                'properties': {
                    'typetext': 'HAIL',
                    'magnitude': '1.5',
                    'wfo': 'FFC',
                    'valid': '2025-10-15T14:30:00Z'
                },
                'geometry': {
                    'coordinates': [-83.2785, 30.8327]  # matches Valdosta 31602
                }
            }
        ]
    }
    
    # Mock DB
    mock_conn = mock_connect.return_value
    mock_conn.row_factory = None
    mock_cursor = mock_conn.execute.return_value
    # First call: SELECT DISTINCT postal_code
    # Second call: SELECT 1 FROM storm_events
    mock_cursor.fetchall.return_value = [{"postal_code": "31602"}]
    mock_cursor.fetchone.return_value = None  # Not exists
    
    with patch('scripts.cron_storm_ingest.Path.exists', return_value=True):
        with patch('builtins.open', create=True) as mock_open:
            import json, io
            mock_open.return_value = io.StringIO(json.dumps({
                "31602": {"lat": 30.8327, "lon": -83.2785}
            }))
            fetch_storm_data()
            
    # Verify execute was called for INSERT
    insert_calls = [
        call for call in mock_conn.execute.mock_calls 
        if "INSERT INTO storm_events" in str(call)
    ]
    assert len(insert_calls) == 1
