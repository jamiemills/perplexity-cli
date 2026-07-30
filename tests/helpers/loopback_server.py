"""Minimal loopback HTTP/SSE server for hermetic integration tests.

Binds exclusively to 127.0.0.1 on an ephemeral port.  Tests configure
the response payload before issuing requests through the real API client.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


@dataclass(frozen=True, slots=True)
class SSEResponse:
    """Configurable SSE response for the loopback server."""

    status_code: int = 200
    content_type: str = "text/event-stream"
    sse_chunks: list[dict[str, object]] = field(default_factory=list)
    raw_body: str | None = None


def make_sse_chunks(text: str) -> list[dict[str, object]]:
    """Build a minimal two-chunk SSE sequence that produces *text*."""
    return [
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
                    "markdown_block": {"chunks": [text]},
                },
            ],
            "final_sse_message": True,
        },
    ]


class _Handler(BaseHTTPRequestHandler):
    """Delegates POST handling to the parent LoopbackServer."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""
        self.server.parent.handle_post(self, body)

    def log_message(self, fmt: str, *args: Any) -> None:
        pass


class LoopbackServer(HTTPServer):
    """A hermetic HTTP/SSE server bound to 127.0.0.1 on an ephemeral port."""

    def __init__(self) -> None:
        self.parent: LoopbackServer = self
        super().__init__(("127.0.0.1", 0), _Handler)
        self._thread: threading.Thread | None = None
        self.response: SSEResponse = SSEResponse(sse_chunks=make_sse_chunks("default"))
        self.last_request_body: bytes = b""
        self.request_count: int = 0

    @property
    def url(self) -> str:
        """Return the base URL for this server."""
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self) -> None:
        """Start serving in a daemon thread."""
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Shut down the server and join the thread."""
        self.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def handle_post(self, handler: _Handler, body: bytes) -> None:
        """Record the request and send the configured response."""
        self.request_count += 1
        self.last_request_body = body
        resp = self.response

        if resp.raw_body is not None:
            self._send_raw(handler, resp)
            return

        handler.send_response(resp.status_code)
        handler.send_header("Content-Type", resp.content_type)
        handler.end_headers()
        for chunk in resp.sse_chunks:
            payload = json.dumps(chunk)
            handler.wfile.write(f"event: message\ndata: {payload}\n\n".encode())
            handler.wfile.flush()

    @staticmethod
    def _send_raw(handler: _Handler, resp: SSEResponse) -> None:
        """Send a raw body response with explicit content type."""
        encoded = (resp.raw_body or "").encode("utf-8")
        handler.send_response(resp.status_code)
        handler.send_header("Content-Type", resp.content_type)
        handler.send_header("Content-Length", str(len(encoded)))
        handler.end_headers()
        handler.wfile.write(encoded)
