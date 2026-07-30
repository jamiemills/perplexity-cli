"""Hermetic integration tests for the query protocol chain.

Exercises the full path: API client → request serialisation → loopback
HTTP/SSE server → event parser → model validation → final Answer envelope.
No real network calls are made; an autouse fixture blocks non-loopback
connections at the socket layer.
"""

from __future__ import annotations

import json
import socket
import time

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import Answer, QueryInput
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    UpstreamSchemaError,
)
from tests.helpers.loopback_server import LoopbackServer, SSEResponse, make_sse_chunks

pytestmark = [pytest.mark.hermetic_integration]

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0"})
_RealCreateConnection = socket.create_connection


def _guarded_create_connection(
    address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None
):  # type: ignore[no-untyped-def]
    """Reject non-loopback connections unconditionally."""
    if isinstance(address, tuple) and len(address) >= 2:
        host = str(address[0])
    else:
        host = str(address)

    if host not in _LOOPBACK_HOSTS and not host.startswith("127."):
        msg = f"Hermetic guard: external connection to {host!r} blocked"
        raise OSError(msg)

    return _RealCreateConnection(address, timeout, source_address)


@pytest.fixture(autouse=True)
def _block_external_network():
    """Block all non-loopback socket connections for hermetic tests."""
    socket.create_connection = _guarded_create_connection  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.create_connection = _RealCreateConnection  # type: ignore[assignment]


@pytest.fixture
def loopback():
    """Start a loopback SSE server and stop it after the test."""
    server = LoopbackServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def api_client(loopback: LoopbackServer, monkeypatch: pytest.MonkeyPatch) -> PerplexityAPI:
    """Create a real API client pointed at the loopback server."""
    monkeypatch.setenv("PERPLEXITY_QUERY_ENDPOINT", f"{loopback.url}/api/query")
    from perplexity_cli.utils.config import clear_urls_cache

    clear_urls_cache()
    client = PerplexityAPI(token=None)
    yield client
    client.close()
    clear_urls_cache()


def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace time.sleep with a no-op to speed up retry tests."""
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)


class TestQuerySuccess:
    """Verify the full query chain produces correct output."""

    def test_simple_query_returns_answer(
        self, loopback: LoopbackServer, api_client: PerplexityAPI
    ) -> None:
        """A well-formed SSE stream produces an Answer with expected text."""
        loopback.response = SSEResponse(sse_chunks=make_sse_chunks("Hello hermetic world."))

        answer = api_client.get_complete_answer("test query")

        assert isinstance(answer, Answer)
        assert answer.text == "Hello hermetic world."
        assert loopback.request_count >= 1

    def test_request_body_serialised_correctly(
        self, loopback: LoopbackServer, api_client: PerplexityAPI
    ) -> None:
        """The outbound POST body contains the query string and params."""
        loopback.response = SSEResponse(sse_chunks=make_sse_chunks("ok"))

        list(api_client.submit_query(QueryInput(query="serialise me")))

        body = json.loads(loopback.last_request_body)
        assert body["query_str"] == "serialise me"
        assert "params" in body
        assert isinstance(body["params"], dict)

    def test_multiple_sse_chunks_streamed(
        self, loopback: LoopbackServer, api_client: PerplexityAPI
    ) -> None:
        """All SSE chunks are yielded as individual messages."""
        loopback.response = SSEResponse(sse_chunks=make_sse_chunks("multi"))

        messages = list(api_client.submit_query(QueryInput(query="test")))

        assert len(messages) >= 2
        assert messages[-1].final_sse_message is True

    def test_web_results_extracted_as_references(
        self, loopback: LoopbackServer, api_client: PerplexityAPI
    ) -> None:
        """Web results in the final chunk become Answer references."""
        chunks = make_sse_chunks("answer with refs")
        chunks[-1]["web_results"] = [
            {"name": "Example", "url": "https://example.com", "snippet": "A snippet"},
        ]
        loopback.response = SSEResponse(sse_chunks=chunks)

        answer = api_client.get_complete_answer("test")

        assert len(answer.references) == 1
        assert answer.references[0].name == "Example"


class TestQueryErrors:
    """Verify error handling for non-2xx and malformed responses."""

    def test_500_raises_http_error(
        self,
        loopback: LoopbackServer,
        api_client: PerplexityAPI,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A 500 response raises PerplexityHTTPStatusError."""
        loopback.response = SSEResponse(
            status_code=500,
            content_type="application/json",
            raw_body='{"error": "internal"}',
        )
        _patch_sleep(monkeypatch)

        with pytest.raises(PerplexityHTTPStatusError):
            list(api_client.submit_query(QueryInput(query="test")))

    def test_429_rate_limit_raises(
        self,
        loopback: LoopbackServer,
        api_client: PerplexityAPI,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A 429 rate-limit response raises after retries are exhausted."""
        loopback.response = SSEResponse(
            status_code=429,
            content_type="application/json",
            raw_body='{"error": "rate limit"}',
        )
        _patch_sleep(monkeypatch)

        with pytest.raises(PerplexityHTTPStatusError):
            list(api_client.submit_query(QueryInput(query="test")))

        assert loopback.request_count >= 3

    def test_malformed_sse_body_raises(
        self, loopback: LoopbackServer, api_client: PerplexityAPI
    ) -> None:
        """Non-JSON SSE data raises UpstreamSchemaError."""
        loopback.response = SSEResponse(
            status_code=200,
            content_type="text/event-stream",
            raw_body="event: message\ndata: not valid json\n\n",
        )

        with pytest.raises(UpstreamSchemaError, match="Failed to parse SSE data"):
            list(api_client.submit_query(QueryInput(query="test")))

    def test_no_final_message_raises(
        self, loopback: LoopbackServer, api_client: PerplexityAPI
    ) -> None:
        """A stream without a final SSE message raises UpstreamSchemaError."""
        loopback.response = SSEResponse(
            sse_chunks=[
                {
                    "backend_uuid": "be-1",
                    "status": "IN_PROGRESS",
                    "text_completed": False,
                    "blocks": [],
                    "final_sse_message": False,
                },
            ],
        )

        with pytest.raises(UpstreamSchemaError, match="No final SSE message"):
            api_client.get_complete_answer("test")


class TestNetworkGuard:
    """Verify the autouse guard blocks external connections."""

    def test_external_connection_blocked(self) -> None:
        """Attempting a non-loopback connection raises OSError."""
        with pytest.raises(OSError, match="Hermetic guard"):
            _guarded_create_connection(("93.184.216.34", 80))

    def test_loopback_connection_allowed(self) -> None:
        """Loopback addresses pass through the guard."""
        try:
            _guarded_create_connection(("127.0.0.1", 0))
        except OSError as e:
            if "Hermetic guard" in str(e):
                pytest.fail(f"Guard incorrectly blocked loopback: {e}")
        except ConnectionRefusedError:
            pass
