"""
Unit tests for the AI Service.
"""

import json
import asyncio
from unittest.mock import patch, MagicMock

import pytest
from app.services.ai_service import AIService


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.gemini_api_key = "fake_api_key"
    return settings


@patch("app.services.ai_service.get_settings")
@patch("app.services.ai_service.genai.GenerativeModel")
@patch("app.services.ai_service.genai.configure")
def test_analyze_job_data_success(
    mock_configure, mock_model_class, mock_get_settings, mock_settings
):
    """Test successful JSON parsing from Gemini API."""
    mock_get_settings.return_value = mock_settings

    # Mock the Gemini response
    mock_model_instance = MagicMock()
    mock_response = MagicMock()

    expected_decision = {
        "action": "generate_document",
        "reasoning": "Sufficient details provided.",
        "document_data": {
            "materials": ["Shingles", "Underlayment"],
            "total_cost": 5000.0,
        },
    }
    mock_response.text = json.dumps(expected_decision)
    mock_model_instance.generate_content.return_value = mock_response
    mock_model_class.return_value = mock_model_instance

    service = AIService()
    payload = {"id": "123", "notes": "Need roof replacement"}

    result = asyncio.run(service.analyze_job_data(payload))

    assert result["action"] == "generate_document"
    assert "materials" in result["document_data"]
    assert mock_model_instance.generate_content.called


@patch("app.services.ai_service.get_settings")
@patch("app.services.ai_service.genai.GenerativeModel")
@patch("app.services.ai_service.genai.configure")
def test_analyze_job_data_invalid_json(
    mock_configure, mock_model_class, mock_get_settings, mock_settings
):
    """Test handling of invalid JSON returned by the model."""
    mock_get_settings.return_value = mock_settings

    mock_model_instance = MagicMock()
    mock_response = MagicMock()

    # Simulate a model returning invalid JSON (e.g., Markdown blocks)
    mock_response.text = "```json\n{'invalid': true\n```"
    mock_model_instance.generate_content.return_value = mock_response
    mock_model_class.return_value = mock_model_instance

    service = AIService()
    payload = {"id": "123"}

    result = asyncio.run(service.analyze_job_data(payload))

    # Should gracefully fail and return an error action
    assert result["action"] == "error"
    assert "Failed to parse" in result["reasoning"]
