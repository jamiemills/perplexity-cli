"""Tests for the REST client (non-streaming JSON GET/POST).

Uses mock-based testing to avoid real HTTP requests. New exception-contract
cases use typed fakes at the session boundary rather than unrestricted mocks.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError
from curl_cffi.requests.exceptions import Timeout

from perplexity_cli.api.rest_client import RestClient
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)


class FakeResponse:
    """Typed stand-in for the slice of a curl_cffi response used here."""

    def __init__(
        self,
        *,
        ok: bool = True,
        status_code: int = 200,
        url: str = "https://example.com/api/test",
        text: str = "",
        content: bytes = b"",
        headers: dict[str, str] | None = None,
        json_value: object = None,
        json_error: Exception | None = None,
    ) -> None:
        self.ok = ok
        self.status_code = status_code
        self.url = url
        self.text = text
        self.content = content
        self.headers = headers if headers is not None else {}
        self._json_value = json_value
        self._json_error = json_error

    def json(self) -> object:
        """Return the configured payload or raise the configured error."""
        if self._json_error is not None:
            raise self._json_error
        return self._json_value


class FakeSession:
    """Typed stand-in for the session boundary used by ``get_json``."""

    def __init__(
        self,
        *,
        response: FakeResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.get_calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        """Record the call and return the response or raise the error."""
        self.get_calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("FakeSession requires a response or an error")
        return self.response


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


class TestRestClientExceptionContract:
    """Exact exception types raised by ``get_json`` across the contract."""

    URL = "https://example.com/api/test"

    def test_success_returns_decoded_json(self, client: RestClient) -> None:
        payload: dict[str, object] = {"key": "value"}
        session = FakeSession(response=FakeResponse(json_value=payload))

        with patch.object(client, "_get_client", return_value=session):
            result = client.get_json(self.URL)

        assert result == payload

    def test_404_raises_http_status_error_with_get_context(self, client: RestClient) -> None:
        session = FakeSession(
            response=FakeResponse(ok=False, status_code=404, text="Not Found"),
        )

        with patch.object(client, "_get_client", return_value=session):
            with pytest.raises(PerplexityHTTPStatusError) as exc_info:
                client.get_json(self.URL)

        assert exc_info.value.request.method == "GET"
        assert exc_info.value.request.url == self.URL
        assert exc_info.value.response.status_code == 404

    def test_500_raises_http_status_error_with_get_context(self, client: RestClient) -> None:
        session = FakeSession(
            response=FakeResponse(ok=False, status_code=500, text="Boom"),
        )

        with patch.object(client, "_get_client", return_value=session):
            with pytest.raises(PerplexityHTTPStatusError) as exc_info:
                client.get_json(self.URL)

        assert exc_info.value.request.method == "GET"
        assert exc_info.value.request.url == self.URL
        assert exc_info.value.response.status_code == 500

    def test_connection_error_raises_request_error(self, client: RestClient) -> None:
        transport_error = CurlConnectionError("Connection refused")
        session = FakeSession(error=transport_error)

        with patch.object(client, "_get_client", return_value=session):
            with pytest.raises(PerplexityRequestError) as exc_info:
                client.get_json(self.URL)

        assert exc_info.value.__cause__ is transport_error

    def test_timeout_raises_request_error(self, client: RestClient) -> None:
        transport_error = Timeout("Request timed out")
        session = FakeSession(error=transport_error)

        with patch.object(client, "_get_client", return_value=session):
            with pytest.raises(PerplexityRequestError) as exc_info:
                client.get_json(self.URL)

        assert exc_info.value.__cause__ is transport_error

    def test_malformed_json_raises_upstream_schema_error(self, client: RestClient) -> None:
        decode_error = json.JSONDecodeError("Expecting value", "{not json", 0)
        session = FakeSession(response=FakeResponse(json_error=decode_error))

        with patch.object(client, "_get_client", return_value=session):
            with pytest.raises(UpstreamSchemaError) as exc_info:
                client.get_json(self.URL)

        assert exc_info.value.__cause__ is decode_error

    def test_no_raw_transport_exception_crosses_boundary(self, client: RestClient) -> None:
        session = FakeSession(error=CurlConnectionError("Connection refused"))

        with patch.object(client, "_get_client", return_value=session):
            with pytest.raises(Exception) as exc_info:
                client.get_json(self.URL)

        assert type(exc_info.value) is PerplexityRequestError
