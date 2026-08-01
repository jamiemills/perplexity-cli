"""Real MCP protocol tests over the stdio and streamable HTTP transports.

These tests drive the installed ``mcp`` SDK client (``mcp>=1.28.1,<2.0.0``)
against the real ``FastMCP`` server created by ``create_mcp_server``, without
any real Perplexity traffic: ``run_mcp_query`` is faked at the module boundary
for every tool call.

Lifecycle is bounded throughout:

* startup: 5s (waiting for initialize or HTTP socket readiness)
* request: 10s (per client request, via ``asyncio.wait_for``)
* shutdown: 5s (draining server tasks / uvicorn threads)
* each test must therefore finish well within 30s
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import socket
import sys
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Any

import anyio
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    CallToolResult,
    InitializeResult,
)

from perplexity_cli.mcp_server import (
    _TOOL_OUTPUT_LIMIT,
    MCPQueryResult,
    ServerConfig,
    create_mcp_server,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_STARTUP_TIMEOUT = 5.0
_REQUEST_TIMEOUT = 10.0
_SHUTDOWN_TIMEOUT = 5.0

_MCP_PATH = "/mcp"
_HOST = "127.0.0.1"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _free_loopback_port() -> int:
    """Bind an ephemeral loopback port and release it for the test server.

    ``port=0`` is not supported by the MCP server config, so a concrete free
    port is chosen instead.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_HOST, 0))
        return sock.getsockname()[1]


def _fake_query_result(query: str, mode: str, output_format: str = "markdown") -> MCPQueryResult:
    """Build a deterministic fake upstream result for a query."""
    return MCPQueryResult(
        mode=mode,  # type: ignore[arg-type]
        output_format=output_format,  # type: ignore[arg-type]
        answer=f"answer for {query}",
        rendered_response=f"rendered for {query}",
        references=[],
        reference_count=0,
    )


async def _await_call(coro: Any) -> Any:
    """Await a client request under the bounded 10s request timeout."""
    return await asyncio.wait_for(coro, timeout=_REQUEST_TIMEOUT)


def _content_text(result: CallToolResult) -> str:
    """Join all text content blocks of a tool result."""
    return "\n".join(block.text for block in result.content if hasattr(block, "text"))


class _RecordHandler(logging.Handler):
    """Collect log records for stderr-cleanliness assertions."""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__()
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)


@contextmanager
def _capture_error_records() -> Iterator[list[logging.LogRecord]]:
    """Capture ERROR-level (and above) log records on the root logger."""
    records: list[logging.LogRecord] = []
    handler = _RecordHandler(records)
    handler.setLevel(logging.ERROR)
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    try:
        yield records
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


@contextmanager
def _redirect_stderr() -> Iterator[io.StringIO]:
    """Redirect ``sys.stderr`` into a buffer for the duration of the block."""
    stream = io.StringIO()
    original = sys.stderr
    sys.stderr = stream
    try:
        yield stream
    finally:
        sys.stderr = original


# ---------------------------------------------------------------------------
# Transport lifecycle helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _inprocess_stdio_server(
    server: FastMCP,
) -> AsyncIterator[tuple[ClientSession, asyncio.Task[None]]]:
    """Run the FastMCP server in-process over stdio-style memory streams.

    The lowlevel MCP server loop runs as a task on the test loop; the client
    session is connected directly through memory streams so ``run_mcp_query``
    can still be faked at the module boundary.  Shutdown is a graceful EOF:
    the client write stream is closed, the server loop drains and completes,
    and only if that stalls is the task cancelled.
    """
    client_write_writer, server_read = anyio.create_memory_object_stream(0)
    server_write, client_read = anyio.create_memory_object_stream(0)
    server_task = asyncio.create_task(
        server._mcp_server.run(
            server_read,
            server_write,
            server._mcp_server.create_initialization_options(),
        ),
        name="mcp-stdio-server",
    )
    try:
        async with ClientSession(client_read, client_write_writer) as session:
            yield session, server_task
    finally:
        body_exc = sys.exception()
        for stream in (client_write_writer, client_read):
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(stream.aclose(), timeout=_SHUTDOWN_TIMEOUT)
        server_exc: BaseException | None = None
        try:
            await asyncio.wait_for(server_task, timeout=_SHUTDOWN_TIMEOUT)
        except TimeoutError:
            server_task.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(server_task, timeout=_SHUTDOWN_TIMEOUT)
        except BaseException as exc:
            server_exc = exc
        if server_exc is not None and body_exc is None:
            raise server_exc


@asynccontextmanager
async def _streamable_http_server(
    server: FastMCP, host: str, port: int
) -> AsyncIterator[uvicorn.Server]:
    """Serve the FastMCP streamable HTTP app in a daemon thread on a loopback port."""
    app = server.streamable_http_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="critical", access_log=False)
    uvicorn_server = uvicorn.Server(config)
    thread = threading.Thread(target=uvicorn_server.run, daemon=True, name="mcp-http-server")
    thread.start()
    deadline = time.monotonic() + _STARTUP_TIMEOUT
    while not uvicorn_server.started:
        if time.monotonic() > deadline:
            thread.join(timeout=_SHUTDOWN_TIMEOUT)
            raise TimeoutError(
                f"MCP streamable HTTP server did not start within {_STARTUP_TIMEOUT}s"
            )
        time.sleep(0.01)
    try:
        yield uvicorn_server
    finally:
        uvicorn_server.should_exit = True
        thread.join(timeout=_SHUTDOWN_TIMEOUT)
        if thread.is_alive():
            raise TimeoutError(
                f"MCP streamable HTTP server failed to shut down within {_SHUTDOWN_TIMEOUT}s"
            )


@asynccontextmanager
async def _http_client_session(url: str) -> AsyncIterator[ClientSession]:
    """Connect a streamable HTTP MCP client to a running server."""
    async with streamable_http_client(url) as (read_stream, write_stream, _session_id):
        async with ClientSession(read_stream, write_stream) as session:
            yield session


async def _run_case(
    transport: str,
    body: Callable[[ClientSession, InitializeResult], Awaitable[None]],
) -> None:
    """Run *body* against an initialized session over the given transport.

    The whole session lifecycle happens inside this single coroutine so anyio
    task groups (used by the SDK client) are entered and exited in the same
    task, which pytest-asyncio fixture splits would violate.
    """
    port = _free_loopback_port()
    server = create_mcp_server(
        ServerConfig(transport=transport, host=_HOST, port=port)  # type: ignore[arg-type]  # owner: test-infrastructure; reason: port is deliberately an int while the SDK type is strict
    )
    if transport == "stdio":
        async with _inprocess_stdio_server(server) as (session, _server_task):
            initialized = await _await_call(session.initialize())
            await body(session, initialized)
        return
    async with _streamable_http_server(server, _HOST, port):
        async with _http_client_session(f"http://{_HOST}:{port}{_MCP_PATH}") as session:
            initialized = await _await_call(session.initialize())
            await body(session, initialized)


# ---------------------------------------------------------------------------
# Initialize + capability negotiation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_initialize_reports_identity_and_capabilities(transport: str) -> None:
    """initialize echoes the server identity, protocol version and tools capability."""

    async def check(session: ClientSession, initialized: InitializeResult) -> None:
        assert initialized.serverInfo.name == "Perplexity CLI"
        assert initialized.protocolVersion == LATEST_PROTOCOL_VERSION
        assert initialized.capabilities.tools is not None
        assert initialized.instructions is not None
        assert "perplexity_quick_info" in initialized.instructions

    await _run_case(transport, check)


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_list_tools_reports_both_tools_with_meta(transport: str) -> None:
    """tools/list exposes both tools with the large-result meta hint."""

    async def check(session: ClientSession, initialized: InitializeResult) -> None:
        result = await _await_call(session.list_tools())
        names = {tool.name for tool in result.tools}
        assert names == {"perplexity_quick_info", "perplexity_deep_info"}
        for tool in result.tools:
            assert tool.meta is not None
            assert tool.meta.get("anthropic/maxResultSizeChars") == _TOOL_OUTPUT_LIMIT
            assert "query" in tool.inputSchema["properties"]
            assert tool.inputSchema["required"] == ["query"]

    await _run_case(transport, check)


# ---------------------------------------------------------------------------
# tools/call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_call_quick_tool_returns_structured_result(
    transport: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid quick query returns a structured, non-error result."""
    monkeypatch.setattr(
        "perplexity_cli.mcp_server.run_mcp_query",
        lambda query, mode, output_format="markdown": _fake_query_result(
            query, mode, output_format
        ),
    )

    async def check(session: ClientSession, initialized: InitializeResult) -> None:
        result = await _await_call(
            session.call_tool(
                "perplexity_quick_info",
                {"query": "What is the capital of France?", "output_format": "plain"},
            )
        )
        assert result.isError is False
        assert result.structuredContent is not None
        assert result.structuredContent["mode"] == "quick"
        assert "capital of France" in result.structuredContent["answer"]
        assert result.structuredContent["reference_count"] == 0

    await _run_case(transport, check)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_call_deep_tool_returns_structured_result(
    transport: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid deep query returns a structured, non-error result."""
    monkeypatch.setattr(
        "perplexity_cli.mcp_server.run_mcp_query",
        lambda query, mode, output_format="markdown": _fake_query_result(
            query, mode, output_format
        ),
    )

    async def check(session: ClientSession, initialized: InitializeResult) -> None:
        result = await _await_call(
            session.call_tool(
                "perplexity_deep_info",
                {"query": "Trace the history of the printing press", "output_format": "markdown"},
            )
        )
        assert result.isError is False
        assert result.structuredContent is not None
        assert result.structuredContent["mode"] == "deep"
        assert "printing press" in result.structuredContent["answer"]

    await _run_case(transport, check)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_call_with_invalid_params_returns_structured_error(transport: str) -> None:
    """Missing required params yield a structured tool error, not a crash."""

    async def check(session: ClientSession, initialized: InitializeResult) -> None:
        result = await _await_call(session.call_tool("perplexity_quick_info", {}))
        assert result.isError is True
        assert "query" in _content_text(result).lower()

    await _run_case(transport, check)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_call_tool_error_path_reports_failure(
    transport: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing upstream query is surfaced as a structured tool error."""

    def boom(query: str, mode: str, output_format: str = "markdown") -> MCPQueryResult:
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr("perplexity_cli.mcp_server.run_mcp_query", boom)

    async def check(session: ClientSession, initialized: InitializeResult) -> None:
        result = await _await_call(
            session.call_tool("perplexity_quick_info", {"query": "anything"})
        )
        assert result.isError is True
        assert "simulated upstream failure" in _content_text(result)

    await _run_case(transport, check)


# ---------------------------------------------------------------------------
# Progress notifications via ctx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_progress_notifications_reported_when_ctx_provided(
    transport: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calling with a progress callback surfaces server-side progress updates."""
    monkeypatch.setattr(
        "perplexity_cli.mcp_server.run_mcp_query",
        lambda query, mode, output_format="markdown": _fake_query_result(
            query, mode, output_format
        ),
    )
    progress: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress_value: float, total: float | None, message: str | None) -> None:
        progress.append((progress_value, total, message))

    async def check(session: ClientSession, initialized: InitializeResult) -> None:
        result = await _await_call(
            session.call_tool(
                "perplexity_quick_info",
                {"query": "quick fact", "output_format": "plain"},
                progress_callback=on_progress,
            )
        )
        assert result.isError is False
        values = [entry[0] for entry in progress]
        assert 0.2 in values
        assert 1.0 in values
        assert all(entry[1] == 1.0 for entry in progress)

    await _run_case(transport, check)


# ---------------------------------------------------------------------------
# Event-loop safety: concurrent calls must not serialise the event loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_concurrent_calls_do_not_block_the_event_loop(
    transport: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two simultaneous tool calls run concurrently (barrier proves no blocking)."""
    barrier = threading.Barrier(2, timeout=_REQUEST_TIMEOUT)

    def concurrent_query(query: str, mode: str, output_format: str = "markdown") -> MCPQueryResult:
        barrier.wait()
        return _fake_query_result(query, mode, output_format)

    monkeypatch.setattr("perplexity_cli.mcp_server.run_mcp_query", concurrent_query)

    async def check(session: ClientSession, initialized: InitializeResult) -> None:
        results = await _await_call(
            asyncio.gather(
                session.call_tool("perplexity_quick_info", {"query": "one"}),
                session.call_tool("perplexity_quick_info", {"query": "two"}),
            )
        )
        assert all(result.isError is False for result in results)

    await _run_case(transport, check)


# ---------------------------------------------------------------------------
# Clean shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clean_shutdown_after_stdio_client_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing the stdio client gracefully terminates the server loop (no cancel)."""
    monkeypatch.setattr(
        "perplexity_cli.mcp_server.run_mcp_query",
        lambda query, mode, output_format="markdown": _fake_query_result(
            query, mode, output_format
        ),
    )
    server = create_mcp_server(ServerConfig(transport="stdio"))
    async with _inprocess_stdio_server(server) as (session, server_task):
        await _await_call(session.initialize())
        result = await _await_call(
            session.call_tool("perplexity_quick_info", {"query": "shutdown probe"})
        )
        assert result.isError is False

    assert server_task.done()
    assert not server_task.cancelled()
    assert server_task.exception() is None


@pytest.mark.asyncio
async def test_clean_shutdown_after_streamable_http_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full HTTP session terminates its session and the uvicorn server cleanly."""
    monkeypatch.setattr(
        "perplexity_cli.mcp_server.run_mcp_query",
        lambda query, mode, output_format="markdown": _fake_query_result(
            query, mode, output_format
        ),
    )
    port = _free_loopback_port()
    server = create_mcp_server(
        ServerConfig(transport="streamable-http", host=_HOST, port=port)  # type: ignore[arg-type]  # owner: test-infrastructure; reason: port is deliberately an int while the SDK type is strict
    )
    async with _streamable_http_server(server, _HOST, port) as http_server:
        assert http_server.started
        async with _http_client_session(f"http://{_HOST}:{port}{_MCP_PATH}") as session:
            await _await_call(session.initialize())
            result = await _await_call(
                session.call_tool("perplexity_quick_info", {"query": "http probe"})
            )
            assert result.isError is False
        assert not http_server.should_exit


# ---------------------------------------------------------------------------
# Stderr cleanliness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_stderr_stays_clean_during_successful_session(
    transport: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful session emits no ERROR-level records and no tracebacks."""
    monkeypatch.setattr(
        "perplexity_cli.mcp_server.run_mcp_query",
        lambda query, mode, output_format="markdown": _fake_query_result(
            query, mode, output_format
        ),
    )
    port = _free_loopback_port()

    async def exercise(session: ClientSession) -> None:
        await _await_call(session.initialize())
        listed = await _await_call(session.list_tools())
        assert len(listed.tools) == 2
        result = await _await_call(
            session.call_tool("perplexity_quick_info", {"query": "clean session"})
        )
        assert result.isError is False

    with _redirect_stderr() as stderr_stream:
        with _capture_error_records() as records:
            server = create_mcp_server(
                ServerConfig(transport=transport, host=_HOST, port=port)  # type: ignore[arg-type]  # owner: test-infrastructure; reason: port is deliberately an int while the SDK type is strict
            )
            if transport == "stdio":
                async with _inprocess_stdio_server(server) as (session, _server_task):
                    await exercise(session)
            else:
                async with _streamable_http_server(server, _HOST, port):
                    async with _http_client_session(f"http://{_HOST}:{port}{_MCP_PATH}") as session:
                        await exercise(session)

    error_records = [record for record in records if record.levelno >= logging.ERROR]
    assert error_records == [], "server emitted error-level log records"
    assert "Traceback" not in stderr_stream.getvalue()
