"""Hermetic integration tests for the query/SSE protocol chain.

Tests the full protocol stack---client request serialisation, SSE parsing,
error handling, retry behaviour, and credential/path redaction---against
the local loopback harness server.  No external network, no real
credentials; the module is marked ``hermetic_integration`` so it never
runs in the ordinary lane.
"""

from __future__ import annotations

import json
import socket
import time
import uuid
from pathlib import Path

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import Answer, QueryInput
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.logging import (
    redact_mapping_keys,
    redact_path,
    redact_text,
    redact_url,
)
from tests.support.protocol_server import ProtocolServer, QueryResponse

pytestmark = [pytest.mark.hermetic_integration]


def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``time.sleep`` with an instant no-op.

    ``threading.Event.wait`` is *not* patched because curl_cffi's internal
    ``ThreadPoolExecutor`` relies on it for thread synchronisation.
    """
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)


class TestSuccessfulQuery:
    """Hermetic tests for successful query flows over the harness."""

    @pytest.mark.usefixtures("harness_config")
    def test_simple_query_returns_answer(self, harness_server: ProtocolServer) -> None:
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("Hello from harness."),
        )

        api = PerplexityAPI(token=None)
        answer = api.get_complete_answer("test query")

        assert isinstance(answer, Answer)
        assert "Hello from harness." in answer.text
        assert harness_server.request_count >= 1

    @pytest.mark.usefixtures("harness_config")
    def test_multiple_sse_chunks_produce_separate_messages(
        self, harness_server: ProtocolServer
    ) -> None:
        """All SSE chunks are emitted as individual SSEMessage objects."""
        chunks = harness_server.make_query_sse_chunks("multi-chunk answer")
        harness_server.query_response = QueryResponse(sse_chunks=chunks)

        api = PerplexityAPI(token=None)
        messages = list(api.submit_query(QueryInput(query="test")))

        assert len(messages) >= 2
        assert messages[-1].final_sse_message is True

    @pytest.mark.usefixtures("harness_config")
    def test_sse_chunks_with_web_results(self, harness_server: ProtocolServer) -> None:
        """SSE chunks can include web_results references."""
        chunks = harness_server.make_query_sse_chunks("answer with refs")
        chunks[-1]["web_results"] = [
            {"name": "Example", "url": "https://example.com", "snippet": "A snippet"},
        ]
        harness_server.query_response = QueryResponse(sse_chunks=chunks)

        api = PerplexityAPI(token=None)
        answer = api.get_complete_answer("test")

        assert len(answer.references) == 1
        assert answer.references[0].name == "Example"
        assert answer.references[0].url == "https://example.com"

    @pytest.mark.usefixtures("harness_config")
    def test_request_body_serialised_correctly(self, harness_server: ProtocolServer) -> None:
        """The outbound POST body matches the expected query request shape."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("ok"),
        )

        api = PerplexityAPI(token=None)
        list(api.submit_query(QueryInput(query="serialise me", attachment_urls=["s3://file1"])))

        body = json.loads(harness_server.last_request_body)
        assert body["query_str"] == "serialise me"
        assert "params" in body
        assert isinstance(body["params"], dict)

    @pytest.mark.usefixtures("harness_config")
    def test_request_body_includes_uuid_fields(self, harness_server: ProtocolServer) -> None:
        """Generated UUID fields are present in the serialised request."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("ok"),
        )

        api = PerplexityAPI(token=None)
        list(api.submit_query(QueryInput(query="uuid test")))

        body = json.loads(harness_server.last_request_body)
        params = body["params"]
        assert "frontend_uuid" in params
        frontend_uuid = params["frontend_uuid"]
        assert isinstance(frontend_uuid, str)
        uuid.UUID(frontend_uuid)

    @pytest.mark.usefixtures("harness_config")
    def test_query_completes_with_text_answer(self, harness_server: ProtocolServer) -> None:
        """A full query round-trip produces a complete Answer with text."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("the complete answer"),
        )

        api = PerplexityAPI(token=None)
        answer = api.get_complete_answer("what is the answer?")

        assert answer.text == "the complete answer"
        assert isinstance(answer.references, list)


class TestErrorHandling:
    """Hermetic tests for error handling in the query protocol."""

    @pytest.mark.usefixtures("harness_config")
    def test_non_2xx_status_raises_http_error(
        self, harness_server: ProtocolServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 500 response raises PerplexityHTTPStatusError."""
        harness_server.query_response = QueryResponse(
            status_code=500,
            content_type="application/json",
            raw_body='{"error": "internal"}',
        )
        _patch_sleep(monkeypatch)

        api = PerplexityAPI(token=None)
        with pytest.raises(PerplexityHTTPStatusError):
            list(api.submit_query(QueryInput(query="test")))

    @pytest.mark.usefixtures("harness_config")
    def test_401_response_raises_http_error(
        self, harness_server: ProtocolServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 401 unauthorised response raises PerplexityHTTPStatusError."""
        harness_server.query_response = QueryResponse(
            status_code=401,
            content_type="application/json",
            raw_body='{"error": "unauthorised"}',
        )
        _patch_sleep(monkeypatch)

        api = PerplexityAPI(token=None)
        with pytest.raises(PerplexityHTTPStatusError):
            list(api.submit_query(QueryInput(query="test")))

    @pytest.mark.usefixtures("harness_config")
    def test_403_response_raises_http_error(
        self, harness_server: ProtocolServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 403 forbidden response raises PerplexityHTTPStatusError."""
        harness_server.query_response = QueryResponse(
            status_code=403,
            content_type="application/json",
            raw_body='{"error": "forbidden"}',
        )
        _patch_sleep(monkeypatch)

        api = PerplexityAPI(token=None)
        with pytest.raises(PerplexityHTTPStatusError):
            list(api.submit_query(QueryInput(query="test")))

    @pytest.mark.usefixtures("harness_config")
    def test_malformed_non_json_sse_raises(self, harness_server: ProtocolServer) -> None:
        """A 200 response with non-JSON SSE body raises an appropriate error."""
        harness_server.query_response = QueryResponse(
            status_code=200,
            content_type="text/event-stream",
            raw_body="event: message\ndata: not valid json\n\n",
        )

        api = PerplexityAPI(token=None)
        with pytest.raises(UpstreamSchemaError, match="Failed to parse SSE data"):
            list(api.submit_query(QueryInput(query="test")))

    @pytest.mark.usefixtures("harness_config")
    def test_malformed_sse_non_object_data_raises(self, harness_server: ProtocolServer) -> None:
        """SSE data that parses to a JSON array (not object) raises UpstreamSchemaError."""
        harness_server.query_response = QueryResponse(
            status_code=200,
            content_type="text/event-stream",
            raw_body='event: message\ndata: ["array", "not", "object"]\n\n',
        )

        api = PerplexityAPI(token=None)
        with pytest.raises(UpstreamSchemaError, match="SSE data must decode to a JSON object"):
            list(api.submit_query(QueryInput(query="test")))


class TestRetryWithFakeClock:
    """Tests for retry behaviour driven through the harness server's fake clock."""

    @pytest.mark.usefixtures("harness_config")
    def test_retry_on_503_exhausts_attempts(
        self, harness_server: ProtocolServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 503 response triggers retries until max_retries is exhausted."""
        harness_server.query_response = QueryResponse(
            status_code=503,
            content_type="application/json",
            raw_body='{"error": "unavailable"}',
        )
        _patch_sleep(monkeypatch)

        api = PerplexityAPI(token=None)
        with pytest.raises(PerplexityHTTPStatusError):
            list(api.submit_query(QueryInput(query="test")))

        assert harness_server.request_count >= 3

    @pytest.mark.usefixtures("harness_config")
    def test_retry_on_429_exhausts_attempts(
        self, harness_server: ProtocolServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 429 rate limit triggers retries then raises."""
        harness_server.query_response = QueryResponse(
            status_code=429,
            content_type="application/json",
            raw_body='{"error": "rate limit"}',
        )
        _patch_sleep(monkeypatch)

        api = PerplexityAPI(token=None)
        with pytest.raises(PerplexityHTTPStatusError):
            list(api.submit_query(QueryInput(query="test")))

        assert harness_server.request_count >= 3

    @pytest.mark.usefixtures("harness_config")
    def test_retry_advances_fake_clock(
        self, harness_server: ProtocolServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sleep during retries advances the harness's fake clock."""
        harness_server.fake_now = 0.0
        harness_server.query_response = QueryResponse(
            status_code=503,
            content_type="application/json",
            raw_body='{"error": "unavailable"}',
        )

        def _fake_sleep(seconds: float) -> None:
            harness_server.advance_clock(seconds)

        monkeypatch.setattr(time, "sleep", _fake_sleep)

        api = PerplexityAPI(token=None)
        with pytest.raises(PerplexityHTTPStatusError):
            list(api.submit_query(QueryInput(query="test")))

        assert harness_server.request_count >= 3
        assert harness_server.fake_now is not None
        assert harness_server.fake_now > 0

    @pytest.mark.usefixtures("harness_config")
    def test_no_retry_on_401(
        self, harness_server: ProtocolServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 401 error is not retried---it fails immediately."""
        harness_server.query_response = QueryResponse(
            status_code=401,
            content_type="application/json",
            raw_body='{"error": "unauthorised"}',
        )
        _patch_sleep(monkeypatch)

        api = PerplexityAPI(token=None)
        with pytest.raises(PerplexityHTTPStatusError):
            list(api.submit_query(QueryInput(query="test")))

        assert harness_server.request_count == 1


class TestRedaction:
    """Tests for credential and path redaction during logging."""

    def test_redact_url_strips_path_and_query(self) -> None:
        """URL redaction keeps only scheme and host."""
        result = redact_url("https://api.example.com/v1/query?token=secret")
        assert result == "https://api.example.com/<redacted>"

    def test_redact_url_empty_input(self) -> None:
        """Empty or None URLs produce a safe sentinel."""
        assert redact_url(None) == "<empty-url>"
        assert redact_url("") == "<empty-url>"

    def test_redact_url_non_http(self) -> None:
        """Non-HTTP strings are fully redacted when the regex doesn't match."""
        result = redact_url("ftp://example.com/path")
        assert result == "<redacted-url>"

    def test_redact_path_shows_filename_only(self) -> None:
        """Path redaction shows only the filename."""
        result = redact_path(Path("/home/user/secrets/token.json"))
        assert result == str(Path("<redacted>") / "token.json")
        assert "secrets" not in result

    def test_redact_path_none_input(self) -> None:
        """None paths produce a safe sentinel."""
        assert redact_path(None) == "<none>"

    def test_redact_text_preserves_length(self) -> None:
        """Text redaction shows a bounded character count."""
        result = redact_text("my secret api key", max_length=32)
        assert "<redacted:" in result
        assert "chars>" in result
        assert "secret" not in result

    def test_redact_text_empty(self) -> None:
        """Empty or None text produces a safe sentinel."""
        assert redact_text(None) == "<empty>"
        assert redact_text("") == "<empty>"

    def test_redact_mapping_keys_shows_count_only(self) -> None:
        """Mapping redaction reveals only the key count."""
        cookies = {"session": "abc123", "cf_clearance": "clear", "csrftoken": "csrf"}
        result = redact_mapping_keys(cookies)
        assert result == "<redacted:3 keys>"
        assert "abc123" not in result
        assert "clear" not in result

    def test_redact_mapping_keys_none_input(self) -> None:
        """None mappings produce a safe sentinel."""
        assert redact_mapping_keys(None) == "<none>"


class TestUpstreamHandling:
    """Edge-case tests for upstream response handling."""

    @pytest.mark.usefixtures("harness_config")
    def test_no_final_sse_message_raises(self, harness_server: ProtocolServer) -> None:
        """Stream without a final SSE message raises UpstreamSchemaError."""
        harness_server.query_response = QueryResponse(
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

        api = PerplexityAPI(token=None)
        with pytest.raises(UpstreamSchemaError, match="No final SSE message"):
            api.get_complete_answer("test")

    @pytest.mark.usefixtures("harness_config")
    def test_empty_blocks_in_final_message_raises(self, harness_server: ProtocolServer) -> None:
        """Final message with empty blocks raises UpstreamSchemaError."""
        harness_server.query_response = QueryResponse(
            sse_chunks=[
                {
                    "backend_uuid": "be-1",
                    "status": "COMPLETE",
                    "text_completed": True,
                    "blocks": [],
                    "final_sse_message": True,
                },
            ],
        )

        api = PerplexityAPI(token=None)
        with pytest.raises(UpstreamSchemaError, match="No answer found"):
            api.get_complete_answer("test")

    @pytest.mark.usefixtures("harness_config")
    def test_empty_query_string_raises_valueerror(self, harness_server: ProtocolServer) -> None:
        """An empty query string raises ValueError before making a request."""
        harness_server.query_response = QueryResponse(
            sse_chunks=harness_server.make_query_sse_chunks("ok"),
        )

        api = PerplexityAPI(token=None)
        with pytest.raises(ValueError, match="Query must not be empty"):
            list(api.submit_query(QueryInput(query="")))

        assert harness_server.request_count == 0


class TestNetworkGuard:
    """The fail-closed guard rejects external connections and allows loopback."""

    def test_external_connection_blocked(self) -> None:
        """Attempting a non-loopback connection raises OSError."""
        with pytest.raises(OSError, match="Network guard"):
            socket.create_connection(("93.184.216.34", 80))

    def test_loopback_connection_allowed(self) -> None:
        """Loopback addresses pass through the guard."""
        try:
            socket.create_connection(("127.0.0.1", 0))
        except OSError as exc:
            if "Network guard" in str(exc):
                pytest.fail(f"Guard incorrectly blocked loopback: {exc}")
        except ConnectionRefusedError:
            pass
