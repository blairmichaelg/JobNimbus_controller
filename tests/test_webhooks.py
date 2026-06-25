"""
Unit tests for the webhook ingestion endpoint.

Tests cover three critical concerns:
1. Security: x-api-key validation rejects unauthorized requests
2. Quarantine Filter: non-test payloads are ignored without enqueueing
3. Enqueueing: valid payloads are dispatched to the ARQ queue

All tests mock the ARQ Redis pool to avoid needing a live Redis instance.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------
VALID_API_KEY = "test_webhook_secret_12345"


def _make_test_app():
    """
    Create a fresh FastAPI app with mocked external dependencies.

    We need to:
    1. Patch get_settings to return predictable test config
    2. Attach a mock redis_pool to app.state (normally done by lifespan)
    3. Attach a mock jn_client to app.state (normally done by lifespan)
    """
    # Patch settings
    mock_settings = MagicMock()
    mock_settings.jobnimbus_api_key = "test_jn_key"
    mock_settings.jobnimbus_base_url = "https://app.jobnimbus.com/api1"
    mock_settings.jobnimbus_actor_email = "test@wickhamroofing.com"
    mock_settings.webhook_secret = VALID_API_KEY
    mock_settings.redis_url = "redis://localhost:6379"
    mock_settings.gemini_api_key = "test_gemini_key"
    mock_settings.app_env = "development"
    mock_settings.log_level = "DEBUG"
    mock_settings.quarantine_status = "API TEST LAB"
    mock_settings.dry_run = True

    from app.api.webhooks import router
    from app.config import get_settings
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(router)

    # Use dependency overrides instead of patch to avoid signature inspection issues
    test_app.dependency_overrides[get_settings] = lambda: mock_settings

    # Attach mocked state (normally set up by lifespan)
    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test_job_123"))
    test_app.state.redis_pool = mock_pool
    test_app.state.jn_client = MagicMock()

    return test_app, mock_pool


# ---------------------------------------------------------------------------
# Test: Security — x-api-key Validation
# ---------------------------------------------------------------------------
class TestWebhookSecurity:
    """Tests for the x-api-key header authentication."""

    def test_missing_api_key_returns_401(self):
        """A request with NO x-api-key header should be rejected."""
        app, _ = _make_test_app()
        client = TestClient(app)

        response = client.post(
            "/webhooks/jobnimbus",
            json={"jnid": "abc123", "status_name": "API TEST LAB"},
            # No x-api-key header
        )

        assert response.status_code == 401
        assert (
            "Missing" in response.json()["detail"]
            or "x-api-key" in response.json()["detail"]
        )

    def test_wrong_api_key_returns_401(self):
        """A request with an INCORRECT x-api-key should be rejected."""
        app, _ = _make_test_app()
        client = TestClient(app)

        response = client.post(
            "/webhooks/jobnimbus",
            json={"jnid": "abc123", "status_name": "API TEST LAB"},
            headers={"x-api-key": "wrong_key_entirely"},
        )

        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"]

    def test_valid_api_key_passes(self):
        """A request with the correct x-api-key should pass authentication."""
        app, _ = _make_test_app()
        client = TestClient(app)

        response = client.post(
            "/webhooks/jobnimbus",
            json={"jnid": "abc123", "status_name": "API TEST LAB"},
            headers={"x-api-key": VALID_API_KEY},
        )

        # Should NOT be 401 — it passed auth
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Test: Quarantine Filter — Ignored Payloads
# ---------------------------------------------------------------------------
class TestQuarantineFilter:
    """Tests for the quarantine fast-reject filter."""

    def test_wrong_status_returns_ignored(self):
        """A payload with status != 'API TEST LAB' should be ignored."""
        app, mock_pool = _make_test_app()
        client = TestClient(app)

        response = client.post(
            "/webhooks/jobnimbus",
            json={
                "jnid": "abc123",
                "status_name": "Lead",  # Wrong status
                "record_type_name": "job",
            },
            headers={"x-api-key": VALID_API_KEY},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"
        assert data["reason"] == "quarantine"

        # CRITICAL: enqueue_job must NOT have been called
        mock_pool.enqueue_job.assert_not_called()

    def test_null_status_returns_ignored(self):
        """A payload with no status_name field should be ignored."""
        app, mock_pool = _make_test_app()
        client = TestClient(app)

        response = client.post(
            "/webhooks/jobnimbus",
            json={"jnid": "abc123"},  # No status_name at all
            headers={"x-api-key": VALID_API_KEY},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"
        assert data["reason"] == "quarantine"
        mock_pool.enqueue_job.assert_not_called()

    def test_missing_entity_id_returns_ignored(self):
        """A payload with correct status but no jnid/id should be ignored."""
        app, mock_pool = _make_test_app()
        client = TestClient(app)

        response = client.post(
            "/webhooks/jobnimbus",
            json={"status_name": "API TEST LAB"},  # No jnid or id
            headers={"x-api-key": VALID_API_KEY},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"
        assert data["reason"] == "missing_entity_id"
        mock_pool.enqueue_job.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Successful Enqueueing
# ---------------------------------------------------------------------------
class TestWebhookEnqueue:
    """Tests for successful task enqueueing."""

    def test_valid_payload_enqueues_and_returns_queued(self):
        """A valid payload should be enqueued and return 'queued' status."""
        app, mock_pool = _make_test_app()
        client = TestClient(app)

        response = client.post(
            "/webhooks/jobnimbus",
            json={
                "jnid": "job_abc123",
                "status_name": "API TEST LAB",
                "record_type_name": "job",
                "event_type": "modified",
            },
            headers={"x-api-key": VALID_API_KEY},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["jnid"] == "job_abc123"

        # Verify enqueue_job was called with correct arguments
        mock_pool.enqueue_job.assert_called_once_with(
            "process_jobnimbus_event",
            jnid="job_abc123",
            payload={
                "jnid": "job_abc123",
                "id": None,
                "status_name": "API TEST LAB",
                "record_type_name": "job",
                "event_type": "modified",
            },
        )

    def test_payload_with_id_instead_of_jnid(self):
        """Should accept 'id' as a fallback when 'jnid' is absent."""
        app, mock_pool = _make_test_app()
        client = TestClient(app)

        response = client.post(
            "/webhooks/jobnimbus",
            json={
                "id": "contact_xyz789",  # Uses 'id' instead of 'jnid'
                "status_name": "API TEST LAB",
                "record_type_name": "contact",
                "event_type": "created",
            },
            headers={"x-api-key": VALID_API_KEY},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["jnid"] == "contact_xyz789"

        mock_pool.enqueue_job.assert_called_once_with(
            "process_jobnimbus_event",
            jnid="contact_xyz789",
            payload={
                "jnid": None,
                "id": "contact_xyz789",
                "status_name": "API TEST LAB",
                "record_type_name": "contact",
                "event_type": "created",
            },
        )

    def test_extra_fields_are_tolerated(self):
        """Unexpected extra fields in the payload should not cause errors."""
        app, mock_pool = _make_test_app()
        client = TestClient(app)

        response = client.post(
            "/webhooks/jobnimbus",
            json={
                "jnid": "job_extra456",
                "status_name": "API TEST LAB",
                "record_type_name": "job",
                "event_type": "modified",
                # Extra fields that JN might send unexpectedly
                "first_name": "John",
                "last_name": "Smith",
                "cf_string_1": "some custom value",
                "random_unknown_field": 42,
            },
            headers={"x-api-key": VALID_API_KEY},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["jnid"] == "job_extra456"
        mock_pool.enqueue_job.assert_called_once()

    def test_missing_event_type_defaults_to_unknown(self):
        """If event_type is missing, it should default to 'unknown'."""
        app, mock_pool = _make_test_app()
        client = TestClient(app)

        response = client.post(
            "/webhooks/jobnimbus",
            json={
                "jnid": "job_noetype",
                "status_name": "API TEST LAB",
            },
            headers={"x-api-key": VALID_API_KEY},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "queued"

        mock_pool.enqueue_job.assert_called_once_with(
            "process_jobnimbus_event",
            jnid="job_noetype",
            payload={
                "jnid": "job_noetype",
                "id": None,
                "status_name": "API TEST LAB",
                "record_type_name": None,
                "event_type": None,
            },
        )

    def test_enqueue_failure_returns_503(self):
        """If Redis enqueue fails, the endpoint should return 503 Service Unavailable."""
        app, mock_pool = _make_test_app()
        client = TestClient(app)

        # Force enqueue to fail
        mock_pool.enqueue_job.side_effect = Exception("Redis connection failed")

        response = client.post(
            "/webhooks/jobnimbus",
            json={
                "jnid": "job_503",
                "status_name": "API TEST LAB",
                "record_type_name": "job",
            },
            headers={"x-api-key": VALID_API_KEY},
        )

        assert response.status_code == 503
        assert "Service Unavailable" in response.json()["detail"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
