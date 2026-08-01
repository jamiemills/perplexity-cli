"""Tests for the local loopback protocol server harness."""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from tests.support.protocol_server import (
    REQUEST_TIMEOUT,
    SHUTDOWN_TIMEOUT,
    TEST_TIMEOUT,
    ProtocolServer,
    QueryResponse,
    UploadPutResponse,
    UploadUrlResponse,
    fake_time_monotonic,
)


@pytest.fixture
def server() -> ProtocolServer:
    srv = ProtocolServer()
    srv.start()
    try:
        yield srv
    finally:
        srv.stop()


class TestQueryStreaming:
    def test_basic_query_returns_sse(self, server: ProtocolServer) -> None:
        """A POST to the query endpoint returns controlled SSE chunks."""
        server.query_response = QueryResponse(
            sse_chunks=server.make_query_sse_chunks("hello world"),
        )

        resp = httpx.post(
            f"{server.url}/api/query",
            json={"query_str": "test", "params": {}},
            timeout=REQUEST_TIMEOUT,
        )

        assert resp.status_code == 200
        assert "event-stream" in resp.headers["content-type"]
        body = resp.text
        assert "hello world" in body
        assert "event: message" in body
        assert "data:" in body

    def test_query_parses_to_valid_sse(self, server: ProtocolServer) -> None:
        """The SSE response can be parsed into individual events."""
        chunks = server.make_query_sse_chunks("parse test")
        server.query_response = QueryResponse(sse_chunks=chunks)

        resp = httpx.post(
            f"{server.url}/api/query",
            json={"query_str": "test", "params": {}},
            timeout=REQUEST_TIMEOUT,
        )

        events = _parse_sse(resp.text)
        assert len(events) >= 1
        final = events[-1]
        assert final.get("status") == "COMPLETE"
        assert final.get("final_sse_message") is True

    def test_query_with_web_results(self, server: ProtocolServer) -> None:
        """SSE chunks can include web_results block references."""
        chunks = server.make_query_sse_chunks("with refs")
        chunks[0]["web_results"] = [
            {"name": "Example", "url": "https://example.com", "snippet": "A snippet"},
        ]
        server.query_response = QueryResponse(sse_chunks=chunks)

        resp = httpx.post(
            f"{server.url}/api/query",
            json={"query_str": "test", "params": {}},
            timeout=REQUEST_TIMEOUT,
        )

        events = _parse_sse(resp.text)
        assert "web_results" in events[0]

    def test_query_chunking_boundaries_preserved(self, server: ProtocolServer) -> None:
        """SSE event boundaries are preserved between chunks."""
        chunks = [
            {
                "backend_uuid": "be-1",
                "status": "IN_PROGRESS",
                "text_completed": False,
                "blocks": [],
                "final_sse_message": False,
            },
            {
                "backend_uuid": "be-1",
                "status": "IN_PROGRESS",
                "text_completed": False,
                "blocks": [],
                "final_sse_message": False,
            },
            {
                "backend_uuid": "be-1",
                "status": "COMPLETE",
                "text_completed": True,
                "blocks": [
                    {
                        "intended_usage": "ask_text",
                        "markdown_block": {"chunks": ["final answer"]},
                    }
                ],
                "final_sse_message": True,
            },
        ]

        server.query_response = QueryResponse(sse_chunks=chunks)

        resp = httpx.post(
            f"{server.url}/api/query",
            json={"query_str": "test", "params": {}},
            timeout=REQUEST_TIMEOUT,
        )

        events = _parse_sse(resp.text)
        assert len(events) == 3
        assert events[0]["status"] == "IN_PROGRESS"
        assert events[2]["status"] == "COMPLETE"

    def test_query_custom_status_code(self, server: ProtocolServer) -> None:
        """The server honours a custom error status code."""
        server.query_response = QueryResponse(
            status_code=500,
            content_type="application/json",
            raw_body='{"error": "internal"}',
        )

        resp = httpx.post(
            f"{server.url}/api/query",
            json={"query_str": "test", "params": {}},
            timeout=REQUEST_TIMEOUT,
        )

        assert resp.status_code == 500
        assert resp.json() == {"error": "internal"}

    def test_query_custom_headers(self, server: ProtocolServer) -> None:
        """Custom headers are sent on the query response."""
        server.query_response = QueryResponse(
            sse_chunks=server.make_query_sse_chunks("test"),
            headers={"X-Custom": "harness-value"},
        )

        resp = httpx.post(
            f"{server.url}/api/query",
            json={"query_str": "test", "params": {}},
            timeout=REQUEST_TIMEOUT,
        )

        assert resp.headers.get("x-custom") == "harness-value"


class TestUploadUrl:
    def test_get_upload_url(self, server: ProtocolServer) -> None:
        """GET to upload URL endpoint returns JSON."""
        server.upload_url_response = UploadUrlResponse(
            body=server.make_upload_url_response(["uuid-1"]),
        )

        resp = httpx.get(f"{server.url}/api/upload-url", timeout=REQUEST_TIMEOUT)

        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "uuid-1" in data["results"]
        assert "fields" in data["results"]["uuid-1"]
        assert "s3_object_url" in data["results"]["uuid-1"]

    def test_post_upload_url(self, server: ProtocolServer) -> None:
        """POST to upload URL endpoint also works."""
        server.upload_url_response = UploadUrlResponse(
            body=server.make_upload_url_response(["uuid-2"]),
        )

        resp = httpx.post(
            f"{server.url}/api/upload-url",
            json={"files": {"uuid-2": {"filename": "f.txt"}}},
            timeout=REQUEST_TIMEOUT,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "uuid-2" in data["results"]

    def test_upload_url_custom_status(self, server: ProtocolServer) -> None:
        """Upload URL endpoint honours custom status codes."""
        server.upload_url_response = UploadUrlResponse(
            status_code=401,
            body={"error": "unauthorised"},
        )

        resp = httpx.get(f"{server.url}/api/upload-url", timeout=REQUEST_TIMEOUT)

        assert resp.status_code == 401

    def test_upload_url_multiple_files(self, server: ProtocolServer) -> None:
        """Upload URL response supports multiple file UUIDs."""
        server.upload_url_response = UploadUrlResponse(
            body=server.make_upload_url_response(["a", "b", "c"]),
        )

        resp = httpx.get(f"{server.url}/api/upload-url", timeout=REQUEST_TIMEOUT)

        data = resp.json()
        assert len(data["results"]) == 3
        assert set(data["results"].keys()) == {"a", "b", "c"}


class TestUploadPut:
    def test_basic_upload_returns_204(self, server: ProtocolServer) -> None:
        """A PUT upload returns 204 No Content."""
        server.upload_put_response = UploadPutResponse(status_code=204)

        resp = httpx.put(
            f"{server.url}/upload",
            content=b"file bytes here",
            timeout=REQUEST_TIMEOUT,
        )

        assert resp.status_code == 204

    def test_upload_collects_bytes(self, server: ProtocolServer) -> None:
        """The server captures uploaded file bytes for verification."""
        server.upload_put_response = UploadPutResponse(status_code=204)

        httpx.put(
            f"{server.url}/upload",
            content=b"my file content",
            timeout=REQUEST_TIMEOUT,
        )

        assert server.last_upload_bytes == b"my file content"

    def test_upload_custom_status(self, server: ProtocolServer) -> None:
        """Upload endpoint returns configurable status codes."""
        server.upload_put_response = UploadPutResponse(
            status_code=400,
            body="invalid file",
        )

        resp = httpx.put(
            f"{server.url}/upload",
            content=b"bad",
            timeout=REQUEST_TIMEOUT,
        )

        assert resp.status_code == 400
        assert resp.text == "invalid file"


class TestFakeClock:
    def test_fake_now_defaults_to_none(self) -> None:
        """When not set, fake_now is None."""
        with ProtocolServer() as srv:
            assert srv.fake_now is None

    def test_set_and_advance_fake_now(self, server: ProtocolServer) -> None:
        """The fake clock can be set and advanced."""
        server.fake_now = 100.0
        assert server.fake_now == 100.0

        server.advance_clock(25.5)
        assert server.fake_now == 125.5

    def test_fake_time_monotonic_falls_back_to_real(self) -> None:
        """When fake_now is None, returns real time.monotonic()."""
        with ProtocolServer() as srv:
            t = fake_time_monotonic(srv)
            assert isinstance(t, float)
            assert t > 0

    def test_fake_time_monotonic_uses_fake_clock(self) -> None:
        """When fake_now is set, returns the fake value."""
        with ProtocolServer() as srv:
            srv.fake_now = 42.0
            assert fake_time_monotonic(srv) == 42.0


class TestServerLifecycle:
    def test_start_and_stop(self) -> None:
        """The server can be started and stopped cleanly."""
        srv = ProtocolServer()
        srv.start()
        assert srv._started
        srv.stop()
        assert not srv._started

    def test_stop_is_idempotent(self) -> None:
        """Calling stop() more than once is safe."""
        srv = ProtocolServer()
        srv.start()
        srv.stop()
        srv.stop()

    def test_context_manager_manages_lifecycle(self) -> None:
        """The context manager starts and stops the server."""
        with ProtocolServer() as srv:
            resp = httpx.get(f"{srv.url}/api/upload-url", timeout=REQUEST_TIMEOUT)
            assert resp.status_code == 200
        thread = srv._thread
        assert thread is not None
        assert not thread.is_alive()

    def test_no_thread_leak_after_stop(self) -> None:
        """The serve thread is joined and not left running after stop()."""
        srv = ProtocolServer()
        srv.start()
        serve_thread = srv._thread
        assert serve_thread is not None
        assert serve_thread.is_alive()
        srv.stop()
        assert not serve_thread.is_alive()

    def test_port_released_after_stop(self) -> None:
        """The listening socket is closed so the port can be reused."""
        srv = ProtocolServer()
        srv.start()
        port = srv.server_address[1]
        srv.stop()

        srv2 = ProtocolServer(port=port)
        srv2.start()
        try:
            assert srv2.server_address[1] == port
            resp = httpx.get(f"{srv2.url}/api/upload-url", timeout=REQUEST_TIMEOUT)
            assert resp.status_code == 200
        finally:
            srv2.stop()

    def test_reset_clears_state(self, server: ProtocolServer) -> None:
        """reset() clears accumulated state."""
        server.upload_put_response = UploadPutResponse()

        httpx.put(
            f"{server.url}/upload",
            content=b"before reset",
            timeout=REQUEST_TIMEOUT,
        )
        assert server.last_upload_bytes == b"before reset"

        server.reset()
        assert server.last_upload_bytes == b""
        assert server.request_count == 0

    def test_multiple_requests_increment_counter(self, server: ProtocolServer) -> None:
        """request_count increments across requests."""
        for _ in range(3):
            httpx.post(
                f"{server.url}/api/query",
                json={"query_str": "test", "params": {}},
                timeout=REQUEST_TIMEOUT,
            )
        assert server.request_count == 3

    def test_concurrent_requests_served_threaded(self, server: ProtocolServer) -> None:
        """Concurrent requests are served in parallel, not serially."""
        server.handler_sleep = 0.3
        barrier = threading.Barrier(5, timeout=TEST_TIMEOUT)
        results: list[str] = []

        def _make_request() -> None:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                results.append("barrier-broken")
                return
            try:
                resp = httpx.post(
                    f"{server.url}/api/query",
                    json={"query_str": "test", "params": {}},
                    timeout=REQUEST_TIMEOUT,
                )
                results.append(str(resp.status_code))
            except Exception as exc:
                results.append(f"error:{exc}")

        threads = [threading.Thread(target=_make_request) for _ in range(5)]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=TEST_TIMEOUT)
        elapsed = time.monotonic() - started

        assert results == ["200"] * 5
        assert server.request_count == 5
        assert elapsed < 1.0, "requests appear to have been served serially"

    def test_no_handler_errors_on_normal_requests(self, server: ProtocolServer) -> None:
        """Well-formed requests do not record handler errors."""
        httpx.post(
            f"{server.url}/api/query",
            json={"query_str": "test", "params": {}},
            timeout=REQUEST_TIMEOUT,
        )
        server.assert_no_handler_errors()

    def test_handler_exception_propagates(self) -> None:
        """A handler failure is recorded and re-raised so the test fails."""
        srv = ProtocolServer()
        srv.handler_exception = RuntimeError("harness boom")
        srv.start()
        try:
            with pytest.raises(httpx.HTTPError):
                httpx.post(
                    f"{srv.url}/api/query",
                    json={"query_str": "test", "params": {}},
                    timeout=REQUEST_TIMEOUT,
                )
            errors = srv.wait_for_handler_errors(timeout=SHUTDOWN_TIMEOUT)
            assert len(errors) >= 1
            assert any("harness boom" in str(error) for error in errors)
        finally:
            with pytest.raises(RuntimeError, match="harness boom"):
                srv.stop()


def _parse_sse(body: str) -> list[dict]:
    """Parse an SSE text body into a list of data dictionaries."""
    events: list[dict] = []
    data_lines: list[str] = []
    for line in body.split("\n"):
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif line == "" and data_lines:
            events.append(json.loads("\n".join(data_lines)))
            data_lines = []
    if data_lines:
        events.append(json.loads("\n".join(data_lines)))
    return events
