"""Tests for the REST client (non-streaming JSON GET/POST).

Uses mock-based testing to avoid real HTTP requests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from perplexity_cli.api.rest_client import RestClient
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
)


@pytest.fixture
def auth_ctx() -> AuthContext:
    """Return an AuthContext with a dummy token."""
    return AuthContext(token="test-token-123", cookies={"csrftoken": "csrf-abc"})


@pytest.fixture
def client(auth_ctx: AuthContext) -> RestClient:
    """Return a RestClient with mock-friendly auth."""
    return RestClient(auth=auth_ctx)


class TestRestClientHeaders:
    """Verify headers are constructed correctly."""

    def test_headers_include_auth_token(self, client: RestClient) -> None:
        headers = client.get_headers()
        assert headers["Authorization"] == "Bearer test-token-123"

    def test_headers_include_csrf_token(self, client: RestClient) -> None:
        headers = client.get_headers()
        assert headers["X-CSRFToken"] == "csrf-abc"

    def test_headers_include_content_type(self, client: RestClient) -> None:
        headers = client.get_headers()
        assert headers["Content-Type"] == "application/json"

    def test_headers_without_token(self) -> None:
        client = RestClient(auth=AuthContext(token=None))
        headers = client.get_headers()
        assert "Authorization" not in headers


class TestRestClientGetJson:
    """Tests for the get_json method."""

    def test_successful_get(self, client: RestClient) -> None:
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"key": "value"}

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_session):
            result = client.get_json("https://example.com/api/test")

        assert result == {"key": "value"}
        mock_session.get.assert_called_once()

    def test_401_raises_http_error(self, client: RestClient) -> None:
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.url = "https://example.com/api/test"

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        with (
            patch.object(client, "_get_client", return_value=mock_session),
            pytest.raises(PerplexityHTTPStatusError),
        ):
            client.get_json("https://example.com/api/test")

    def test_403_raises_http_error(self, client: RestClient) -> None:
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_response.url = "https://example.com/api/test"

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        with (
            patch.object(client, "_get_client", return_value=mock_session),
            pytest.raises(PerplexityHTTPStatusError),
        ):
            client.get_json("https://example.com/api/test")

    def test_cookies_passed_to_request(self, client: RestClient) -> None:
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {}

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_session):
            client.get_json("https://example.com/api/test")

        call_kwargs = mock_session.get.call_args
        assert "cookies" in call_kwargs.kwargs


class TestRestClientClose:
    """Tests for session lifecycle management."""

    def test_close_without_open(self, client: RestClient) -> None:
        """Closing without opening should not raise."""
        client.close()

    def test_context_manager(self, auth_ctx: AuthContext) -> None:
        with RestClient(auth=auth_ctx) as rest_client:
            assert rest_client is not None

    def test_get_client_creates_session(self, client: RestClient) -> None:
        """Lazy session creation via _get_client."""
        with patch(
            "perplexity_cli.utils.session_factory.create_sync_session",
        ) as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value = mock_session

            session = client._get_client()

            assert session is mock_session
            mock_factory.assert_called_once_with(timeout=None)

    def test_get_client_reuses_session(self, client: RestClient) -> None:
        """Second call returns the same session without creating a new one."""
        with patch(
            "perplexity_cli.utils.session_factory.create_sync_session",
        ) as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value = mock_session

            first = client._get_client()
            second = client._get_client()

            assert first is second
            assert mock_factory.call_count == 1

    def test_close_with_active_session(self, client: RestClient) -> None:
        """Close calls close() on the active session and clears it."""
        with patch(
            "perplexity_cli.utils.session_factory.create_sync_session",
        ) as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value = mock_session

            client._get_client()
            client.close()

            mock_session.close.assert_called_once()
            assert client._client is None
