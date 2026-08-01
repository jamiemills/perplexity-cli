"""Local loopback HTTP/SSE protocol server for hermetic integration testing.

Provides controlled responses for the Perplexity API's three protocol
surfaces: SSE query streaming, upload URL acquisition, and S3 file upload.

The server is threaded (one handler thread per request), its captured
state is lock-protected, and worker failures are recorded and propagated
so a handler error fails the owning test rather than vanishing.
"""

from __future__ import annotations

import errno
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# Timeout budgets (seconds) shared by the harness and its lifecycle tests.
STARTUP_TIMEOUT: float = 2.0
REQUEST_TIMEOUT: float = 5.0
SHUTDOWN_TIMEOUT: float = 5.0
TEST_TIMEOUT: float = 30.0


@dataclass
class QueryResponse:
    """Controlled SSE response for a query POST."""

    status_code: int = 200
    content_type: str = "text/event-stream"
    sse_chunks: list[dict[str, object]] = field(default_factory=list)
    raw_body: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class UploadUrlResponse:
    """Controlled upload URL acquisition response."""

    status_code: int = 200
    body: dict[str, object] = field(default_factory=dict)


@dataclass
class UploadPutResponse:
    """Controlled file upload (PUT) response."""

    status_code: int = 204
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)


_DEFAULT_QUERY: QueryResponse = QueryResponse(
    sse_chunks=[
        {
            "backend_uuid": "be-1",
            "context_uuid": "ctx-1",
            "uuid": "req-1",
            "frontend_context_uuid": "fctx-1",
            "display_model": "test",
            "mode": "COPILOT",
            "status": "IN_PROGRESS",
            "text_completed": False,
            "blocks": [],
            "final_sse_message": False,
        },
        {
            "backend_uuid": "be-1",
            "context_uuid": "ctx-1",
            "uuid": "req-1",
            "frontend_context_uuid": "fctx-1",
            "display_model": "test",
            "mode": "COPILOT",
            "status": "COMPLETE",
            "text_completed": True,
            "blocks": [
                {
                    "intended_usage": "ask_text",
                    "markdown_block": {"chunks": ["Hello from harness."]},
                },
            ],
            "final_sse_message": True,
        },
    ],
)

_BENIGN_HANDLER_ERRORS: tuple[type[BaseException], ...] = (
    BrokenPipeError,
    ConnectionResetError,
    ConnectionAbortedError,
)


def _is_benign_handler_error(error: BaseException) -> bool:
    """Return True when *error* is a client-abort transport failure.

    A client that stops reading (for example an early ``break`` in an SSE
    consumer) can legitimately produce EPIPE/ECONNRESET on the server side.
    These are not harness failures and must not fail the owning test.
    """
    if isinstance(error, _BENIGN_HANDLER_ERRORS):
        return True
    return isinstance(error, OSError) and error.errno in (
        errno.EPIPE,
        errno.ECONNRESET,
        errno.ECONNABORTED,
    )


class _Handler(BaseHTTPRequestHandler):
    """Request handler that delegates to the parent ProtocolServer."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""
        self.server.parent._handle_post(self, body)

    def do_PUT(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""
        self.server.parent._handle_put(self, body)

    def do_GET(self) -> None:
        self.server.parent._handle_get(self)

    def log_message(self, fmt: str, *args: Any) -> None:
        pass


class ProtocolServer(ThreadingHTTPServer):
    """A hermetic threaded HTTP/SSE server bound to localhost.

    Tests configure canned responses via properties before issuing
    requests.  Query POSTs return controlled SSE streams; upload URL
    endpoints return JSON; upload PUTs collect file bytes.  Requests are
    served concurrently on a daemon thread per request, captured state is
    lock-protected, and handler failures are recorded so they can fail the
    test instead of vanishing.

    Example:
        server = ProtocolServer()
        server.start()
        server.query_response = QueryResponse(
            sse_chunks=[{"status": "COMPLETE", ...}],
        )
        # issue requests to server.url ...
        server.stop()
    """

    allow_reuse_address = True
    daemon_threads = True
    block_on_close = True

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._host = host
        self.parent: ProtocolServer = self
        super().__init__((host, port), _Handler)
        self._thread: threading.Thread | None = None
        self._started: bool = False
        self._stopped: bool = False
        self._state_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._clock_lock = threading.Lock()
        self._fake_now: float | None = None
        self._handler_errors: list[BaseException] = []

        # Test hooks: an artificial per-request delay and an optional
        # exception the handler raises before serving each request.
        self.handler_sleep: float = 0.0
        self.handler_exception: BaseException | None = None

        self.query_response: QueryResponse = QueryResponse(
            sse_chunks=[dict(c) for c in _DEFAULT_QUERY.sse_chunks],
        )
        self.upload_url_response: UploadUrlResponse = UploadUrlResponse()
        self.upload_put_response: UploadPutResponse = UploadPutResponse()

        self.last_request_body: bytes = b""
        self.last_request_path: str = ""
        self.last_upload_bytes: bytes = b""
        self.request_count: int = 0

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.server_address[1]}"

    @property
    def fake_now(self) -> float | None:
        with self._clock_lock:
            return self._fake_now

    @fake_now.setter
    def fake_now(self, value: float | None) -> None:
        with self._clock_lock:
            self._fake_now = value

    def advance_clock(self, seconds: float) -> None:
        with self._clock_lock:
            if self._fake_now is not None:
                self._fake_now += seconds

    def __enter__(self) -> ProtocolServer:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.stop()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._started:
                return
            self._started = True
            self._stopped = False
            self._thread = threading.Thread(
                target=self.serve_forever,
                daemon=True,
                name="pxcli-protocol-server",
            )
            self._thread.start()
        self._assert_started_within(STARTUP_TIMEOUT)

    def stop(self) -> None:
        """Shut down the server, join worker threads and close sockets.

        Idempotent: repeated calls are no-ops.  Bounded joins assert the
        serve thread actually exits, then recorded non-benign handler
        failures are re-raised so a worker failure fails the test.
        """
        with self._lifecycle_lock:
            if self._stopped:
                return
            self._stopped = True
            was_started = self._started
            self._started = False
            thread = self._thread

        if was_started and thread is not None:
            self.shutdown()
            thread.join(timeout=SHUTDOWN_TIMEOUT)
            if thread.is_alive():
                raise RuntimeError(
                    f"protocol server thread failed to join within {SHUTDOWN_TIMEOUT}s"
                )

        self.server_close()
        for error in self.handler_errors():
            if not _is_benign_handler_error(error):
                raise error

    def _assert_started_within(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        thread = self._thread
        while time.monotonic() < deadline:
            if thread is not None and thread.is_alive():
                return
            time.sleep(0.005)
        raise RuntimeError(f"protocol server failed to start within {timeout}s")

    def reset(self) -> None:
        with self._state_lock:
            self.query_response = QueryResponse(
                sse_chunks=[dict(c) for c in _DEFAULT_QUERY.sse_chunks],
            )
            self.upload_url_response = UploadUrlResponse()
            self.upload_put_response = UploadPutResponse()
            self.last_request_body = b""
            self.last_request_path = ""
            self.last_upload_bytes = b""
            self.request_count = 0

    def handler_errors(self) -> list[BaseException]:
        """Return a snapshot of exceptions raised by request handlers."""
        with self._state_lock:
            return list(self._handler_errors)

    def wait_for_handler_errors(self, timeout: float = SHUTDOWN_TIMEOUT) -> list[BaseException]:
        """Wait up to *timeout* seconds for a handler error to be recorded."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            errors = self.handler_errors()
            if errors:
                return errors
            time.sleep(0.01)
        return self.handler_errors()

    def assert_no_handler_errors(self) -> None:
        """Raise the first non-benign handler error, if any."""
        for error in self.handler_errors():
            if not _is_benign_handler_error(error):
                raise error

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc = sys.exc_info()[1]
        if exc is not None:
            self._record_handler_error(exc)

    def _record_handler_error(self, error: BaseException) -> None:
        with self._state_lock:
            self._handler_errors.append(error)

    def _handle_post(self, handler: _Handler, body: bytes) -> None:
        self._raise_if_configured_failure()
        self._delay_response()
        with self._state_lock:
            self.request_count += 1
            self.last_request_body = body
            self.last_request_path = handler.path

        if handler.path.startswith("/api/upload-url"):
            self._serve_upload_url(handler, body)
        else:
            self._serve_query(handler, body)

    def _handle_put(self, handler: _Handler, body: bytes) -> None:
        self._raise_if_configured_failure()
        self._delay_response()
        with self._state_lock:
            self.request_count += 1
            self.last_request_body = body
            self.last_upload_bytes = body
            self.last_request_path = handler.path

        self._serve_upload_put(handler, body)

    def _handle_get(self, handler: _Handler) -> None:
        self._raise_if_configured_failure()
        self._delay_response()
        with self._state_lock:
            self.request_count += 1
            self.last_request_path = handler.path

        if handler.path.startswith("/api/upload-url"):
            self._serve_upload_url_get(handler)

    def _raise_if_configured_failure(self) -> None:
        failure = self.handler_exception
        if failure is not None:
            raise failure

    def _delay_response(self) -> None:
        delay = self.handler_sleep
        if delay > 0:
            time.sleep(delay)

    def _serve_query(self, handler: _Handler, body: bytes) -> None:
        resp = self.query_response
        if resp.raw_body is not None:
            self._send(handler, resp.status_code, resp.raw_body, resp.content_type, resp.headers)
            return

        handler.send_response(resp.status_code)
        handler.send_header("Content-Type", resp.content_type)
        for key, value in resp.headers.items():
            handler.send_header(key, value)
        handler.end_headers()

        for chunk in resp.sse_chunks:
            data = json.dumps(chunk)
            handler.wfile.write(f"event: message\ndata: {data}\n\n".encode())
            handler.wfile.flush()

    def _serve_upload_url(self, handler: _Handler, body: bytes) -> None:
        resp = self.upload_url_response
        body_json = json.dumps(resp.body)
        self._send(handler, resp.status_code, body_json, "application/json")

    def _serve_upload_url_get(self, handler: _Handler) -> None:
        resp = self.upload_url_response
        body_json = json.dumps(resp.body)
        self._send(handler, resp.status_code, body_json, "application/json")

    def _serve_upload_put(self, handler: _Handler, body: bytes) -> None:
        resp = self.upload_put_response
        self._send(handler, resp.status_code, resp.body, "application/octet-stream", resp.headers)

    @staticmethod
    def _send(
        handler: _Handler,
        status: int,
        body: str,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        encoded = body.encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(encoded)))
        if extra_headers:
            for key, value in extra_headers.items():
                handler.send_header(key, value)
        handler.end_headers()
        handler.wfile.write(encoded)

    def make_query_sse_chunks(
        self,
        text: str,
        *,
        final: bool = True,
        status: str = "COMPLETE",
        include_ask_text_block: bool = True,
    ) -> list[dict[str, object]]:
        """Build a minimal set of SSE chunks for a query answer."""
        blocks: list[dict[str, object]] = []
        if include_ask_text_block:
            blocks = [
                {
                    "intended_usage": "ask_text",
                    "markdown_block": {"chunks": [text]},
                },
            ]

        messages: list[dict[str, object]] = [
            {
                "backend_uuid": "be-1",
                "context_uuid": "ctx-1",
                "uuid": "req-1",
                "frontend_context_uuid": "fctx-1",
                "display_model": "test",
                "mode": "COPILOT",
                "status": "IN_PROGRESS" if blocks else status,
                "text_completed": False,
                "blocks": [],
                "final_sse_message": False,
            },
        ]

        if blocks:
            messages.append(
                {
                    "backend_uuid": "be-1",
                    "context_uuid": "ctx-1",
                    "uuid": "req-1",
                    "frontend_context_uuid": "fctx-1",
                    "display_model": "test",
                    "mode": "COPILOT",
                    "status": status,
                    "text_completed": True,
                    "blocks": blocks,
                    "final_sse_message": final,
                }
            )

        return messages

    def make_upload_url_response(
        self,
        file_uuids: list[str],
        *,
        s3_object_url: str = "https://s3.example.com/obj",
        extra_fields: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Build an upload URL response body for the given file UUIDs."""
        fields: dict[str, str] = {"key": "value"}
        if extra_fields:
            fields.update(extra_fields)

        results: dict[str, dict[str, object]] = {}
        for uuid_str in file_uuids:
            results[uuid_str] = {
                "fields": dict(fields),
                "s3_object_url": f"{s3_object_url}/{uuid_str}",
            }
        return {"results": results}


def fake_time_monotonic(server: ProtocolServer) -> float:
    """Return the fake clock time when set, otherwise real monotonic time."""
    now = server.fake_now
    if now is not None:
        return now
    return time.monotonic()
