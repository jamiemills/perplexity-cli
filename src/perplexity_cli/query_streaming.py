"""Streaming query response handler.

This module contains the logic for streaming query responses from the
Perplexity API in real-time, extracted from cli.py for independent testability.

The module lives in the application layer and therefore imports only from
domain, ports, and shared_pure modules. Presentation output is routed through
injected formatter objects (see ``_StreamRenderContext``) plus the stdlib
streams, and error translation is kept local until the wave-2 wiring
(``query_runner``) provides the adapter implementation.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final, Protocol

from perplexity_cli.api.models import (
    Answer,
    QueryInput,
    SSEMessage,
    TraceContext,
    WebResult,
)
from perplexity_cli.envelope import Meta
from perplexity_cli.ndjson import NDJSONWriter
from perplexity_cli.ports import QueryGateway
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.version import get_version

if TYPE_CHECKING:
    #: Type for error handler callbacks in the dispatch table.
    _ErrorHandler = Callable[[Any, logging.Logger], Any]


class _StreamOutputOptions(Protocol):
    """Structural subset of ``formatting.context.OutputOptions`` used here."""

    json_mode: bool
    strip_references: bool
    output_format: str


class _StreamFormatter(Protocol):
    """Structural subset of the formatter interface used for streaming."""

    def render_complete(  # nosemgrep: boolean-flag-argument  # owner: quality-infrastructure; reason: structural protocol mirrors the formatter interface signature
        self, answer: Answer, strip_references: bool = False
    ) -> None:
        """Render a complete answer directly (rich path)."""
        ...

    def format_references(self, references: list[WebResult]) -> str:
        """Format the references list into a string."""
        ...


class _StreamRenderContext(Protocol):
    """Structural subset of ``formatting.context.RenderContext`` used here."""

    @property
    def formatter(self) -> _StreamFormatter: ...

    @property
    def options(self) -> _StreamOutputOptions: ...


_HTTP_ERROR_MESSAGES: Final[dict[int, str]] = {
    401: "[ERROR] Authentication failed. Token may be expired.",
    403: "[ERROR] Access forbidden. Check your permissions.",
    429: "[ERROR] Rate limit exceeded. Please wait and try again.",
}

_HTTP_ERROR_EXTRAS: Final[dict[int, str]] = {
    401: "\nRe-authenticate with: perplexity-cli auth",
}


def _get_stream_logger() -> logging.Logger:
    """Return the stdlib logger used by the streaming module."""
    return logging.getLogger("perplexity_cli.query_streaming")


def _write_stdout(text: str) -> None:
    """Write *text* to stdout and flush, mirroring ``click.echo(nl=False)``."""
    sys.stdout.write(text)
    sys.stdout.flush()


def _write_stderr(text: str) -> None:
    """Write *text* to stderr and flush, mirroring ``click.echo(err=True)``."""
    sys.stderr.write(text)
    sys.stderr.flush()


def _process_stream_message(
    message: SSEMessage,
    accumulated_text: str,
    ndjson_writer: NDJSONWriter | None,
) -> str:
    """Handle a single SSE message, emitting output and returning updated text.

    Snapshot contract:
    - an empty snapshot emits nothing;
    - a snapshot identical to the accumulated text emits nothing;
    - a strict prefix extension emits exactly the new suffix;
    - a shortened or divergent (non-prefix) snapshot raises
      ``UpstreamSchemaError`` before any output is emitted.

    Args:
        message: The SSE message to process.
        accumulated_text: Text accumulated so far.
        ndjson_writer: Optional NDJSON writer for JSON mode.

    Returns:
        The updated accumulated text.

    Raises:
        UpstreamSchemaError: If the snapshot is not a strict prefix extension.
    """
    text = message.extract_answer_text()
    if not text or text == accumulated_text:
        return accumulated_text

    if not text.startswith(accumulated_text):
        msg = (
            "Streaming snapshot is not a strict prefix extension of the "
            f"accumulated text (accumulated {len(accumulated_text)} characters, "
            f"received {len(text)})"
        )
        raise UpstreamSchemaError(msg)

    new_text = text[len(accumulated_text) :]
    if ndjson_writer:
        ndjson_writer.chunk(new_text)
    else:
        _write_stdout(new_text)
    return text


def _write_ndjson_result(
    ndjson_writer: NDJSONWriter,
    accumulated_text: str,
    references: list[WebResult],
    trace: TraceContext,
) -> None:
    """Write the final NDJSON result event with envelope metadata.

    Args:
        ndjson_writer: The NDJSON writer instance.
        accumulated_text: The complete answer text.
        references: List of web references.
        trace: Trace and timing context for envelope metadata.
    """
    result_data = {
        "answer": accumulated_text,
        "references": [{"name": r.name, "url": r.url, "snippet": r.snippet} for r in references],
    }
    effective_start = trace.start_time if trace.start_time is not None else time.monotonic()
    meta = Meta(
        duration_ms=int((time.monotonic() - effective_start) * 1000),
        version=get_version(),
        trace_id=trace.trace_id or "",
    )
    ndjson_writer.result(
        ok=True,
        command="pxcli query --json --stream",
        result=result_data,
        extras=(meta.model_dump(mode="json"), None, False),
    )


def _render_stream_references(
    render: _StreamRenderContext,
    accumulated_text: str,
    references: list[WebResult],
) -> None:
    """Render references after streaming completes (non-JSON mode).

    Args:
        render: Formatter and output options.
        accumulated_text: The complete answer text.
        references: List of web references.
    """
    _write_stdout("\n")
    if not references or render.options.strip_references:
        return

    _write_stdout("\n")
    if render.options.output_format == "rich":
        render.formatter.render_complete(
            Answer(text=accumulated_text, references=references),
            strip_references=True,
        )
    else:
        formatted_refs = render.formatter.format_references(references)
        if formatted_refs:
            _write_stdout(formatted_refs + "\n")


def _run_stream_loop(
    api: QueryGateway,
    query_input: QueryInput,
    ndjson_writer: NDJSONWriter | None,
) -> tuple[str, list[WebResult]]:
    """Execute the streaming loop, returning accumulated text and references.

    Args:
        api: PerplexityAPI instance.
        query_input: Query text, optional attachment URLs, and model preference.
        ndjson_writer: Optional NDJSON writer for JSON mode.

    Returns:
        Tuple of (accumulated_text, references).
    """
    logger = _get_stream_logger()
    accumulated_text = ""
    references: list[WebResult] = []

    for message in api.submit_query(query_input):
        logger.debug(
            "Received SSE message: status=%s, final=%s",
            message.status,
            message.final_sse_message,
        )
        accumulated_text = _process_stream_message(message, accumulated_text, ndjson_writer)

        if message.final_sse_message and message.web_results:
            references = message.web_results
            logger.debug("Extracted %s references", len(references))

    return accumulated_text, references


def _handle_stream_http_status_error(
    error: PerplexityHTTPStatusError, logger: logging.Logger
) -> None:
    """Handle an HTTP status error during streaming, exiting with code 1."""
    status = error.response.status_code
    logger.error("HTTP error %s during streaming: %s", status, error)
    _write_stdout("\n")
    message = _HTTP_ERROR_MESSAGES.get(status, f"[ERROR] HTTP error {status}.")
    _write_stderr(message + "\n")
    if status in _HTTP_ERROR_EXTRAS:
        _write_stderr(_HTTP_ERROR_EXTRAS[status] + "\n")
    raise SystemExit(1)


def _handle_stream_network_error(error: PerplexityRequestError, logger: logging.Logger) -> None:
    """Handle a network error during streaming, exiting with code 1."""
    logger.error("Network error during streaming: %s", error)
    _write_stdout("\n")
    _write_stderr("[ERROR] Network error. Please check your internet connection.\n")
    raise SystemExit(1)


def _handle_stream_upstream_schema_error(error: Any, logger: logging.Logger) -> None:
    """Handle a malformed upstream snapshot, exiting with code 1."""
    logger.error("Malformed upstream response during streaming: %s", error)
    _write_stdout("\n")
    _write_stderr(f"[ERROR] Upstream response format changed: {error}\n")
    raise SystemExit(1)


def _handle_stream_keyboard_interrupt(logger: logging.Logger) -> None:
    """Handle a user interrupt during streaming, exiting with code 130."""
    logger.info("Streaming interrupted by user")
    _write_stderr("\n[ERROR] Streaming interrupted.\n")
    raise SystemExit(130)


def _handle_stream_output_error(error: Any, logger: logging.Logger) -> None:
    """Handle a local output failure during streaming, exiting with code 1."""
    logger.error("Streaming output failed: %s", error)
    _write_stdout("\n")
    _write_stderr(f"[ERROR] Failed to render streaming output: {error}\n")
    raise SystemExit(1)


def _handle_stream_unexpected_error(error: Exception, logger: logging.Logger) -> None:
    """Handle an unexpected streaming error, exiting with code 1."""
    logger.error("Unexpected error during streaming: %s", error)
    _write_stderr("[ERROR] An unexpected error occurred.\n")
    _write_stderr("Run with --debug for more information.\n")
    raise SystemExit(1)


def _init_stream_error_handlers() -> list[tuple[type | tuple[type, ...], _ErrorHandler]]:
    """Build the error handler dispatch table (lazily initialised)."""
    return [
        (PerplexityHTTPStatusError, _handle_stream_http_status_error),
        (PerplexityRequestError, _handle_stream_network_error),
        (UpstreamSchemaError, _handle_stream_upstream_schema_error),
        (
            KeyboardInterrupt,
            lambda _error, log: _handle_stream_keyboard_interrupt(log),
        ),
        (OSError, _handle_stream_output_error),
    ]


class _StreamErrorHandlers:
    """Lazily-initialised cache for the stream error handler dispatch table."""

    _cache: list[tuple[type | tuple[type, ...], _ErrorHandler]] | None = None

    @classmethod
    def get(cls) -> list[tuple[type | tuple[type, ...], _ErrorHandler]]:
        """Return the error handler dispatch table, building it on first access."""
        if cls._cache is None:
            cls._cache = _init_stream_error_handlers()
        return cls._cache


def _handle_stream_error(error: Exception) -> None:
    """Handle errors raised during streaming, exiting as appropriate.

    Args:
        error: The exception that was raised.
    """
    logger = _get_stream_logger()
    for exc_types, handler in _StreamErrorHandlers.get():
        if isinstance(error, exc_types):
            handler(error, logger)
            return

    _handle_stream_unexpected_error(error, logger)


def stream_query_response(
    api: QueryGateway,
    query_input: QueryInput,
    render: _StreamRenderContext,
    trace: TraceContext,
) -> None:
    """Stream query response in real-time.

    Args:
        api: PerplexityAPI instance.
        query_input: Query text, optional attachment URLs, and model preference.
        render: Formatter and output presentation options.
        trace: Trace and timing context.
    """
    ndjson_writer = None
    if render.options.json_mode:
        ndjson_writer = NDJSONWriter(sys.stdout)
        ndjson_writer.start(command="pxcli query --json --stream")

    try:
        accumulated_text, references = _run_stream_loop(
            api,
            query_input,
            ndjson_writer,
        )
        if ndjson_writer:
            _write_ndjson_result(ndjson_writer, accumulated_text, references, trace)
        else:
            _render_stream_references(render, accumulated_text, references)
    except Exception as e:  # catch-all CLI error handler
        _handle_stream_error(e)
