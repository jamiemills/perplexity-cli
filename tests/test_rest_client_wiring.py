"""Request-wiring and diagnostic-logging tests for ``RestClient``.

Every outbound GET is inspected through a recording fake session so the
exact headers, cookies, URL and timeout reaching the transport are
pinned, alongside the failure-message contract and the DEBUG request log.
"""

from __future__ import annotations

import logging
import re

import pytest
from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

from perplexity_cli.api.rest_client import RestClient
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.utils.cookies import to_curl_cffi_cookies
from perplexity_cli.utils.exceptions import PerplexityRequestError


class _RecordingSession:
    """Fake transport recording GET calls instead of performing them."""

    def __init__(
        self,
        response: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> object:
        """Record the call, then answer or raise as configured."""
        self.calls.append((url, kwargs))
        if self._error is not None:
            raise self._error
        return self._response

    def close(self) -> None:
        """Close the fake transport."""


class _JsonResponse:
    """Minimal successful response returning a fixed JSON payload."""

    def __init__(self) -> None:
        self.ok = True

    def json(self) -> object:
        return {"t008": True}


AUTH = AuthContext(
    token="t008-rest-token",
    cookies={"cf_clearance": "t008-rest-cookie"},
)
URL = "https://api.example.test/rest/t008"


def _wired_client(timeout: int | None = 33) -> tuple[RestClient, _RecordingSession]:
    client = RestClient(auth=AUTH, timeout=timeout)
    session = _RecordingSession(response=_JsonResponse())
    client._client = session  # type: ignore[assignment]  # owner: test-infrastructure; reason: inject the recording session at the HTTP boundary
    return client, session


class TestRestClientWiring:
    """Constructor, header and request-forwarding contracts."""

    def test_init_stores_configured_timeout(self) -> None:
        """The configured timeout is kept on the client."""
        client, _ = _wired_client()
        assert client.timeout == 33

    def test_headers_advertise_json_content_and_accept(self) -> None:
        """REST requests send JSON content type and accept headers."""
        client, _ = _wired_client()

        headers = client.get_headers()

        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"

    def test_get_client_passes_timeout_to_session_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The configured timeout reaches the session factory unchanged."""
        recorded: dict[str, object] = {}

        def _factory(**kwargs: object) -> object:
            recorded.update(kwargs)
            return object()

        monkeypatch.setattr("perplexity_cli.utils.session_factory.create_sync_session", _factory)
        client = RestClient(auth=AUTH, timeout=21)
        client._client = None

        client._get_client()

        assert recorded == {"timeout": 21}

    def test_get_json_sends_auth_headers_cookies_url_and_timeout(self) -> None:
        """GET requests forward the full auth context to the transport."""
        client, session = _wired_client()

        result = client.get_json(URL)

        assert result == {"t008": True}
        requested_url, kwargs = session.calls[0]
        assert requested_url == URL
        assert kwargs["headers"] == client.get_headers()
        assert kwargs["cookies"] == to_curl_cffi_cookies(AUTH.cookies)
        assert kwargs["timeout"] == 33


class TestRestClientDiagnosticsAndFailures:
    """DEBUG request log and failure message contracts."""

    def test_get_json_logs_rest_get_line_at_debug_level(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Successful GETs emit the REST GET debug line verbatim."""
        client, _ = _wired_client()

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client.get_json(URL)

        rendered = [record.getMessage() for record in caplog.records]
        assert f"REST GET {URL}" in rendered

    def test_transport_failure_raises_anchored_request_error(
        self,
    ) -> None:
        """Transport failures wrap into an anchored request error."""
        transport_error = CurlConnectionError("t008-refused")
        client = RestClient(auth=AUTH)
        client._client = _RecordingSession(error=transport_error)  # type: ignore[assignment]  # owner: test-infrastructure; reason: inject a failing session to verify transport wrapping

        expected = re.escape(f"REST GET {URL} failed: t008-refused")
        with pytest.raises(PerplexityRequestError, match=rf"^{expected}$") as exc_info:
            client.get_json(URL)

        assert exc_info.value.__cause__ is transport_error

    def test_get_client_reuses_session_until_close(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The REST boundary creates one session and closes that same object."""
        created: list[_RecordingSession] = []

        def _factory(**_: object) -> _RecordingSession:
            session = _RecordingSession(response=_JsonResponse())
            created.append(session)
            return session

        monkeypatch.setattr("perplexity_cli.utils.session_factory.create_sync_session", _factory)
        client = RestClient(auth=AUTH, timeout=21)

        first = client._get_client()
        second = client._get_client()

        assert first is second
        assert len(created) == 1
        client.close()
        assert client._client is None
