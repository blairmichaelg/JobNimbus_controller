import pytest
from unittest.mock import patch, MagicMock
from scripts.cron_storm_ingest import fetch_storm_data

def test_fetch_storm_data_success():
    """Verify that fetch_storm_data parses NWS JSON accurately into storm events."""
    zip_map = {"31602": {"lat": 30.8327, "lon": -83.2785}}
    
    mock_nws_response = {
        "features": [
            {
                "properties": {
                    "event": "Severe Thunderstorm Warning",
                    "sent": "2026-07-31T12:00:00Z",
                    "parameters": {
                        "hailSize": ["1.75"],
                        "windGust": ["60mph"]
                    }
                }
            },
            {
                "properties": {
                    "event": "Flood Warning",
                    "sent": "2026-07-31T12:05:00Z",
                    "parameters": {}
                }
            }
        ]
    }
    
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_nws_response
        mock_get.return_value = mock_resp
        
        events = fetch_storm_data("31602", zip_map)
        
        assert len(events) == 1
        assert events[0]["event_type"] == "SEVERE THUNDERSTORM WARNING"
        assert events[0]["hail_size_inches"] == 1.75
        assert events[0]["wind_speed_mph"] == 60.0
        assert events[0]["source"] == "NWS_API"

def test_fetch_storm_data_handles_missing_zip():
    events = fetch_storm_data("99999", {"12345": {"lat": 0, "lon": 0}})
    assert len(events) == 0

def test_fetch_storm_data_handles_api_error():
    zip_map = {"31602": {"lat": 30.8327, "lon": -83.2785}}
    
    with patch("requests.get") as mock_get:
        mock_get.side_effect = Exception("API Timeout")
        events = fetch_storm_data("31602", zip_map)
        assert len(events) == 0
