"""Local loopback HTTP/SSE protocol server for hermetic integration testing.

Provides controlled responses for the Perplexity API's three protocol
surfaces: SSE query streaming, upload URL acquisition, and S3 file upload.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


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


class ProtocolServer(HTTPServer):
    """A hermetic HTTP/SSE server bound to localhost.

    Tests configure canned responses via properties before issuing
    requests.  Query POSTs return controlled SSE streams; upload URL
    endpoints return JSON; upload PUTs collect file bytes.

    Example:
        server = ProtocolServer()
        server.start()
        server.query_response = QueryResponse(
            sse_chunks=[{"status": "COMPLETE", ...}],
        )
        # issue requests to server.url ...
        server.stop()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._host = host
        self.parent: ProtocolServer = self
        super().__init__((host, port), _Handler)
        self._thread: threading.Thread | None = None
        self._started: bool = False
        self._fake_now: float | None = None
        self._clock_lock = threading.Lock()

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

    def start(self) -> None:
        self._started = True
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._started = False
        self.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def reset(self) -> None:
        self.query_response = QueryResponse(
            sse_chunks=[dict(c) for c in _DEFAULT_QUERY.sse_chunks],
        )
        self.upload_url_response = UploadUrlResponse()
        self.upload_put_response = UploadPutResponse()
        self.last_request_body = b""
        self.last_request_path = ""
        self.last_upload_bytes = b""
        self.request_count = 0

    def _handle_post(self, handler: _Handler, body: bytes) -> None:
        self.request_count += 1
        self.last_request_body = body
        self.last_request_path = handler.path

        if handler.path.startswith("/api/upload-url"):
            self._serve_upload_url(handler, body)
        else:
            self._serve_query(handler, body)

    def _handle_put(self, handler: _Handler, body: bytes) -> None:
        self.request_count += 1
        self.last_request_body = body
        self.last_upload_bytes = body
        self.last_request_path = handler.path

        self._serve_upload_put(handler, body)

    def _handle_get(self, handler: _Handler) -> None:
        self.request_count += 1
        self.last_request_path = handler.path

        if handler.path.startswith("/api/upload-url"):
            self._serve_upload_url_get(handler)

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
