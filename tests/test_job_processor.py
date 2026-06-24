"""
Unit tests for the job processor worker logic.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.workers.job_processor import process_jobnimbus_event


@pytest.fixture
def mock_ctx():
    mock_client = AsyncMock()
    return {"jn_client": mock_client}


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.quarantine_status = "API TEST LAB"
    return settings


@patch("app.workers.job_processor.get_settings")
def test_process_drops_task_if_quarantine_fails(
    mock_get_settings, mock_ctx, mock_settings
):
    """
    If the hydrated canonical data does not match the quarantine status,
    the task should be dropped early.
    """
    mock_get_settings.return_value = mock_settings

    # Mock hydration returning a different status
    mock_ctx["jn_client"].get_job.return_value = {
        "id": "job123",
        "status_name": "In Progress",  # Fails quarantine check
    }

    # Run the worker
    asyncio.run(
        process_jobnimbus_event(
            mock_ctx,
            jnid="job123",
            payload={"event_type": "modified", "record_type_name": "job"},
        )
    )

    # Verify get_job was called
    mock_ctx["jn_client"].get_job.assert_called_once_with("job123")

    # We could also mock logger to verify the warning, but this ensures
    # it exited gracefully without raising exceptions or trying to translate.


@patch("app.workers.job_processor.PDFGenerator")
@patch("app.workers.job_processor.AIService")
@patch("app.workers.job_processor.FieldMapper")
@patch("app.workers.job_processor.get_settings")
def test_process_translates_and_logs_on_quarantine_pass(
    mock_get_settings,
    mock_mapper_class,
    mock_ai_class,
    mock_pdf_class,
    mock_ctx,
    mock_settings,
):
    """
    If quarantine passes, the data should be translated, sent to AI, and
    if action is 'generate_document', PDF should be created and uploaded.
    """
    mock_get_settings.return_value = mock_settings

    # Mock hydration returning correct status
    mock_ctx["jn_client"].get_job.return_value = {
        "id": "job123",
        "status_name": "API TEST LAB",
        "cf_string_1": "State Farm",
    }

    # Mock mapper
    mock_mapper_instance = MagicMock()
    mock_mapper_instance.to_human.return_value = {
        "id": "job123",
        "status_name": "API TEST LAB",
        "insurance_carrier": "State Farm",
    }
    mock_mapper_class.return_value = mock_mapper_instance

    # Mock AI Service
    mock_ai_instance = AsyncMock()
    mock_ai_instance.analyze_job_data.return_value = {
        "action": "generate_document",
        "document_data": {"total_cost": 100},
    }
    mock_ai_class.return_value = mock_ai_instance

    # Mock PDF Generator
    mock_pdf_instance = AsyncMock()
    mock_pdf_instance.generate_estimate_pdf.return_value = "/tmp/fake_path.pdf"
    mock_pdf_class.return_value = mock_pdf_instance

    # We need to mock Path.exists and Path.unlink to prevent actual file ops in the test
    with patch("app.workers.job_processor.Path") as mock_path_class:
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path_class.return_value = mock_path_instance

        # Run the worker
        asyncio.run(
            process_jobnimbus_event(
                mock_ctx,
                jnid="job123",
                payload={"event_type": "modified", "record_type_name": "job"},
            )
        )

    # Verify hydration and translation
    mock_ctx["jn_client"].get_job.assert_called_once_with("job123")
    mock_mapper_instance.to_human.assert_called_once()

    # Verify AI call
    mock_ai_instance.analyze_job_data.assert_called_once()

    # Verify PDF generation
    mock_pdf_instance.generate_estimate_pdf.assert_called_once_with(
        {"total_cost": 100}, "job123"
    )

    # Verify JobNimbus Egress
    mock_ctx["jn_client"].upload_document.assert_called_once_with(
        jnid="job123",
        filepath="/tmp/fake_path.pdf",
        description="AI Generated Estimate",
    )
    mock_ctx["jn_client"].update_job.assert_called_once_with(
        "job123", {"status_name": "Estimate Uploaded"}
    )

    # Verify temp file cleanup
    mock_path_instance.unlink.assert_called_once()


@patch("app.workers.job_processor.get_settings")
def test_process_uses_get_contact_for_contact_records(
    mock_get_settings, mock_ctx, mock_settings
):
    """
    If record_type_name is 'contact', it should call get_contact.
    """
    mock_get_settings.return_value = mock_settings

    # Mock hydration returning incorrect status just to exit early
    mock_ctx["jn_client"].get_contact.return_value = {
        "id": "contact123",
        "status_name": "Different Status",
    }

    # Run the worker
    asyncio.run(
        process_jobnimbus_event(
            mock_ctx,
            jnid="contact123",
            payload={"event_type": "modified", "record_type_name": "contact"},
        )
    )

    # Verify get_contact was called instead of get_job
    mock_ctx["jn_client"].get_contact.assert_called_once_with("contact123")
    mock_ctx["jn_client"].get_job.assert_not_called()


def test_process_raises_runtime_error_if_no_client():
    """
    If the jn_client is not injected into the context, it should raise a RuntimeError.
    """
    with pytest.raises(RuntimeError, match="JobNimbusClient not found"):
        asyncio.run(
            process_jobnimbus_event(
                ctx={},  # Empty context, missing jn_client
                jnid="job123",
                payload={"event_type": "modified"},
            )
        )
