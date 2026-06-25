"""
Unit tests for the JobNimbus API client.

Tests the exponential backoff decorator, query parameter construction,
and DRY_RUN behavior without hitting the real JobNimbus API.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Test: Exponential Backoff Decorator
# ---------------------------------------------------------------------------
class TestRetryOnRateLimit:
    """Tests for the retry_on_rate_limit decorator."""

    def test_successful_request_no_retry(self):
        """A successful request should not trigger any retries."""
        from app.services.jobnimbus_client import retry_on_rate_limit

        call_count = 0

        @retry_on_rate_limit
        async def mock_request():
            nonlocal call_count
            call_count += 1
            return {"status": "ok"}

        result = asyncio.run(mock_request())
        assert result == {"status": "ok"}
        assert call_count == 1

    def test_retries_on_429(self):
        """Should retry on 429 and succeed when the API recovers."""
        from app.services.jobnimbus_client import retry_on_rate_limit

        call_count = 0

        @retry_on_rate_limit
        async def mock_request():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                # Simulate 429 response
                request = httpx.Request("GET", "https://example.com/test")
                response = httpx.Response(429, request=request)
                raise httpx.HTTPStatusError(
                    "Rate limited", request=request, response=response
                )
            return {"status": "recovered"}

        # Patch asyncio.sleep to avoid real delays in tests
        with patch(
            "app.services.jobnimbus_client.asyncio.sleep", new_callable=AsyncMock
        ):
            result = asyncio.run(mock_request())

        assert result == {"status": "recovered"}
        assert call_count == 3  # 2 failures + 1 success

    def test_non_429_error_not_retried(self):
        """Non-429 HTTP errors should propagate immediately without retry."""
        from app.services.jobnimbus_client import retry_on_rate_limit

        call_count = 0

        @retry_on_rate_limit
        async def mock_request():
            nonlocal call_count
            call_count += 1
            request = httpx.Request("GET", "https://example.com/test")
            response = httpx.Response(500, request=request)
            raise httpx.HTTPStatusError(
                "Server error", request=request, response=response
            )

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            asyncio.run(mock_request())

        assert exc_info.value.response.status_code == 500
        assert call_count == 1  # No retry on 500

    def test_max_retries_exhausted(self):
        """Should raise after MAX_RETRIES consecutive 429s."""
        from app.services.jobnimbus_client import retry_on_rate_limit, MAX_RETRIES

        call_count = 0

        @retry_on_rate_limit
        async def mock_request():
            nonlocal call_count
            call_count += 1
            request = httpx.Request("GET", "https://example.com/test")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError(
                "Rate limited", request=request, response=response
            )

        with patch(
            "app.services.jobnimbus_client.asyncio.sleep", new_callable=AsyncMock
        ):
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                asyncio.run(mock_request())

        assert exc_info.value.response.status_code == 429
        assert call_count == MAX_RETRIES


# ---------------------------------------------------------------------------
# Test: Transient Network Error Decorator
# ---------------------------------------------------------------------------
class TestRetryOnTransientNetwork:
    """Tests the exponential backoff decorator for transient network errors."""

    def test_transient_network_error_retried(self):
        """Should retry up to 2 times on httpx.RequestError."""
        from app.services.jobnimbus_client import retry_on_transient_network_errors, MAX_RETRIES

        call_count = 0

        @retry_on_transient_network_errors
        async def mock_request():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                request = httpx.Request("GET", "https://example.com/test")
                raise httpx.RequestError("Connection timeout", request=request)
            return {"status": "recovered"}

        with patch("app.services.jobnimbus_client.asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(mock_request())

        assert result == {"status": "recovered"}
        assert call_count == 3

    def test_max_transient_retries_exhausted(self):
        """Should raise after max transient retries (2)."""
        from app.services.jobnimbus_client import retry_on_transient_network_errors

        call_count = 0

        @retry_on_transient_network_errors
        async def mock_request():
            nonlocal call_count
            call_count += 1
            request = httpx.Request("GET", "https://example.com/test")
            raise httpx.RequestError("Connection timeout", request=request)

        with patch("app.services.jobnimbus_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.RequestError):
                asyncio.run(mock_request())

        assert call_count == 3  # Max transient retries is 3

# ---------------------------------------------------------------------------
# Test: Query Parameter Construction
# ---------------------------------------------------------------------------
class TestQueryParamBuilders:
    """Tests for _read_params and _mutation_params."""

    def _make_client(self):
        """Create a client with mock settings to avoid needing real env vars."""
        from app.services.jobnimbus_client import JobNimbusClient

        mock_settings = MagicMock()
        mock_settings.jobnimbus_api_key = "test_key_123"
        mock_settings.jobnimbus_base_url = "https://app.jobnimbus.com/api1"
        mock_settings.jobnimbus_actor_email = "test@wickhamroofing.com"
        mock_settings.dry_run = True
        mock_settings.log_level = "DEBUG"
        mock_settings.app_env = "development"

        return JobNimbusClient(settings=mock_settings)

    def test_read_params_includes_actor(self):
        """GET requests should include the actor parameter."""
        client = self._make_client()
        params = client._read_params()
        assert params["actor"] == "test@wickhamroofing.com"
        assert "skip" not in params  # Reads should NOT skip automations

    def test_mutation_params_includes_skip_and_actor(self):
        """PUT/POST requests must include both skip and actor."""
        client = self._make_client()
        params = client._mutation_params()
        assert params["skip"] == "automation,notification"
        assert params["actor"] == "test@wickhamroofing.com"

    def test_mutation_params_extra_kwargs(self):
        """Extra kwargs should be merged into mutation params."""
        client = self._make_client()
        params = client._mutation_params(custom_param="value")
        assert params["custom_param"] == "value"
        assert params["skip"] == "automation,notification"

    def test_dry_run_flag_set(self):
        """Client should respect the dry_run setting."""
        client = self._make_client()
        assert client._dry_run is True


# ---------------------------------------------------------------------------
# Test: DRY_RUN Behavior
# ---------------------------------------------------------------------------
class TestDryRunBehavior:
    """Tests that mutations are logged but not executed in DRY_RUN mode."""

    def _make_client(self, dry_run: bool = True):
        from app.services.jobnimbus_client import JobNimbusClient

        mock_settings = MagicMock()
        mock_settings.jobnimbus_api_key = "test_key_123"
        mock_settings.jobnimbus_base_url = "https://app.jobnimbus.com/api1"
        mock_settings.jobnimbus_actor_email = "test@wickhamroofing.com"
        mock_settings.dry_run = dry_run
        mock_settings.log_level = "DEBUG"
        mock_settings.app_env = "development"

        return JobNimbusClient(settings=mock_settings)

    def test_update_job_dry_run_returns_none(self):
        """update_job in DRY_RUN should return None without making HTTP calls."""
        client = self._make_client(dry_run=True)

        async def run():
            return await client.update_job("test_jnid", {"status": "Approved"})

        result = asyncio.run(run())
        assert result is None

    def test_create_task_dry_run_returns_none(self):
        """create_task in DRY_RUN should return None without making HTTP calls."""
        client = self._make_client(dry_run=True)

        async def run():
            return await client.create_task({"title": "Test Task"})

        result = asyncio.run(run())
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
