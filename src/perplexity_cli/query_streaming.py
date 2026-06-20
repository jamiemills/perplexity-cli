"""Streaming query response handler.

This module contains the logic for streaming query responses from the
Perplexity API in real-time, extracted from cli.py for independent testability.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import click
from click import ClickException

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import (
    Answer,
    QueryInput,
    SSEMessage,
    TraceContext,
    WebResult,
)
from perplexity_cli.formatting.context import RenderContext
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.http_errors import (
    handle_http_error,
    handle_network_error,
    handle_unexpected_cli_error,
)
from perplexity_cli.utils.logging import get_logger

if TYPE_CHECKING:
    import logging

    from perplexity_cli.ndjson import NDJSONWriter

    #: Type for error handler callbacks in the dispatch table.
    _ErrorHandler = Callable[[Any, logging.Logger], Any]


def _process_stream_message(
    message: SSEMessage,
    accumulated_text: str,
    ndjson_writer: NDJSONWriter | None,
) -> str:
    """Handle a single SSE message, emitting output and returning updated text.

    Args:
        message: The SSE message to process.
        accumulated_text: Text accumulated so far.
        ndjson_writer: Optional NDJSON writer for JSON mode.

    Returns:
        The updated accumulated text.
    """
    text = message.extract_answer_text()
    if not text or text == accumulated_text:
        return accumulated_text

    new_text = text[len(accumulated_text) :]
    if not new_text:
        return accumulated_text

    if ndjson_writer:
        ndjson_writer.chunk(new_text)
    else:
        click.echo(new_text, nl=False)
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
    from perplexity_cli.envelope import Meta
    from perplexity_cli.utils.version import get_version

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
        meta=meta.model_dump(mode="json"),
    )


def _render_stream_references(
    render: RenderContext,
    accumulated_text: str,
    references: list[WebResult],
) -> None:
    """Render references after streaming completes (non-JSON mode).

    Args:
        render: Formatter and output options.
        accumulated_text: The complete answer text.
        references: List of web references.
    """
    click.echo()
    if not references or render.options.strip_references:
        return

    click.echo()
    if render.options.output_format == "rich":
        render.formatter.render_complete(
            Answer(text=accumulated_text, references=references),
            strip_references=True,
        )
    else:
        formatted_refs = render.formatter.format_references(references)
        if formatted_refs:
            click.echo(formatted_refs)


def _run_stream_loop(
    api: PerplexityAPI,
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
    logger = get_logger()
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


def _init_stream_error_handlers() -> list[tuple[type | tuple[type, ...], _ErrorHandler]]:
    """Build the error handler dispatch table (lazily initialised)."""
    return [
        (
            PerplexityHTTPStatusError,
            lambda e, log: (
                click.echo(),
                handle_http_error(e, log, debug_mode=False, context="during streaming"),
            ),
        ),
        (
            PerplexityRequestError,
            lambda e, log: (
                click.echo(),
                handle_network_error(e, log, debug_mode=False, context="during streaming"),
            ),
        ),
        (
            UpstreamSchemaError,
            lambda e, log: (
                log.error("Malformed upstream response during streaming: %s", e),
                click.echo(),
                click.echo(f"[ERROR] Upstream response format changed: {e}", err=True),
                sys.exit(1),
            ),
        ),
        (
            KeyboardInterrupt,
            lambda e, log: (
                log.info("Streaming interrupted by user"),
                click.echo("\n[ERROR] Streaming interrupted.", err=True),
                sys.exit(130),
            ),
        ),
        (
            (ClickException, OSError),
            lambda e, log: (
                log.error("Streaming output failed: %s", e),
                click.echo(),
                click.echo(f"[ERROR] Failed to render streaming output: {e}", err=True),
                sys.exit(1),
            ),
        ),
    ]


_STREAM_ERROR_HANDLERS: list[tuple[type | tuple[type, ...], _ErrorHandler]] = (
    _init_stream_error_handlers()
)


def _handle_stream_error(error: Exception) -> None:
    """Handle errors raised during streaming, exiting as appropriate.

    Args:
        error: The exception that was raised.
    """
    logger = get_logger()
    for exc_types, handler in _STREAM_ERROR_HANDLERS:
        if isinstance(error, exc_types):
            handler(error, logger)
            return

    click.echo()
    handle_unexpected_cli_error(
        error,
        logger,
        user_message="[ERROR] An unexpected error occurred.",
        log_message="Unexpected error during streaming",
        include_debug_hint=True,
    )


def stream_query_response(
    api: PerplexityAPI,
    query_input: QueryInput,
    render: RenderContext,
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
        from perplexity_cli.ndjson import NDJSONWriter

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
    except Exception as e:
        _handle_stream_error(e)
