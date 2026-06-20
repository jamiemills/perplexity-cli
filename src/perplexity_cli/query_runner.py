"""Query command orchestration helpers.

This module keeps Click wiring in ``cli.py`` thin while preserving the
existing query behaviour.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import click

from perplexity_cli.api.models import QueryInput, TraceContext
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.formatting.context import OutputOptions, RenderContext
from perplexity_cli.utils.async_bridge import run_async
from perplexity_cli.utils.exceptions import (
    AttachmentError,
    AttachmentUploadError,
    ConfigurationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.logging import get_logger, redact_path, redact_text, redact_url

if TYPE_CHECKING:
    from pathlib import Path

    from perplexity_cli.api.endpoints import PerplexityAPI
    from perplexity_cli.api.models import Answer
    from perplexity_cli.formatting.base import Formatter
    from perplexity_cli.utils.attachment_models import FileAttachment


@dataclass(frozen=True, slots=True)
class QueryOptions:
    """Optional flags for :func:`run_query_command`, built from CLI flags."""

    output_format: str | None
    strip_references: bool
    stream: bool
    attachments: tuple[str, ...]
    model_preference: str | None
    request_param_overrides: tuple[str, ...]

_QUERY_JSON_COMMAND = "pxcli query --json"


def _is_uvx_environment() -> bool:
    """Check whether the current environment is a uvx environment."""
    return "UV_ACTIVE" in os.environ or "UVXENV" in os.environ


def _detect_execution_environment() -> str:
    """Detect the current Python execution environment.

    Returns:
        A string identifying the environment type.
    """
    if _is_uvx_environment():
        return "uvx"
    if "VIRTUAL_ENV" in os.environ:
        return "venv"
    if sys.base_prefix != sys.prefix:
        return "virtualenv"
    return "unknown"


def log_query_debug_context(  # nosemgrep: boolean-flag-argument
    query_text: str,
    output_format: str | None,
    stream: bool,
) -> None:
    """Log environment and invocation details for debug runs."""
    logger = get_logger()
    if not logger.isEnabledFor(logging.DEBUG):
        return

    import socket

    from perplexity_cli.utils.config import get_config_paths, get_save_cookies_enabled

    try:
        hostname = socket.gethostname()
        logger.debug("Hostname: %s", hostname)
    except OSError:
        logger.debug("Could not resolve hostname")

    logger.debug("Platform: %s", sys.platform)
    logger.debug("Python version: %s", sys.version.split()[0])
    logger.debug("Python executable: %s", sys.executable)
    logger.debug("Execution environment: %s", _detect_execution_environment())

    token_path = get_config_paths().token_path
    logger.debug(  # nosemgrep: python-logger-credential-disclosure
        "Token path: %s", redact_path(token_path)
    )
    logger.debug(  # nosemgrep: python-logger-credential-disclosure
        "Token exists: %s", token_path.exists()
    )
    logger.debug("Cookie storage enabled: %s", get_save_cookies_enabled())
    logger.debug(
        "Query command invoked: query=%s, format=%s, stream=%s",
        redact_text(query_text),
        output_format,
        stream,
    )


def _has_potential_file_references(query_text: str, attachment_list: list[str]) -> bool:
    """Check whether the query or attachments may reference files.

    Args:
        query_text: The query text.
        attachment_list: List of attachment arguments.

    Returns:
        True if file references are likely present.
    """
    if attachment_list:
        return True
    return "/" in query_text or "\\" in query_text


def resolve_attachment_urls(
    query_text: str,
    attachments_str: tuple[str, ...],
    auth: AuthContext,
) -> list[str]:
    """Load local attachments and upload them when needed."""
    logger = get_logger()
    attachment_list = list(attachments_str)
    if not _has_potential_file_references(query_text, attachment_list):
        return []

    try:
        return _resolve_and_upload(query_text, attachment_list, auth, logger)
    except (FileNotFoundError, AttachmentError, ValueError) as e:
        click.echo(f"[ERROR] Failed to load attachments: {e}", err=True)
        logger.error("Attachment loading failed: %s", e)
        raise SystemExit(1)


def _resolve_and_upload(
    query_text: str,
    attachment_list: list[str],
    auth: AuthContext,
    logger: logging.Logger,
) -> list[str]:
    """Resolve file arguments and upload attachments.

    Args:
        query_text: The query text.
        attachment_list: List of attachment arguments.
        auth: Authentication credentials.
        logger: Logger instance.

    Returns:
        List of uploaded attachment URLs.
    """
    from perplexity_cli.utils.file_handler import resolve_file_arguments

    file_paths = resolve_file_arguments(
        [query_text],
        attach_args=attachment_list if attachment_list else None,
    )
    if not file_paths:
        return []

    logger.debug("Resolving attachments: found %s file(s)", len(file_paths))
    validated_token = _require_auth_for_attachments(auth.token, logger)
    return _load_and_upload_attachments(file_paths, validated_token, auth.cookies, logger)


def _require_auth_for_attachments(token: str | None, logger: logging.Logger) -> str:
    """Validate authentication is present for attachments.

    Args:
        token: The authentication token, or None.
        logger: Logger instance.

    Returns:
        The validated non-None token.

    Raises:
        SystemExit: If authentication is missing.
    """
    if token:
        return token
    click.echo("[ERROR] File attachments require authentication.", err=True)
    click.echo("\nPlease authenticate first with: pxcli auth login", err=True)
    logger.error("Attachment upload attempted without authentication")
    raise SystemExit(1)


def _load_and_upload_attachments(
    file_paths: list[Path],
    token: str,
    cookies: dict[str, str] | None,
    logger: logging.Logger,
) -> list[str]:
    """Load and upload file attachments to S3.

    Args:
        file_paths: Resolved file paths to upload.
        token: Validated authentication token.
        cookies: Browser cookies.
        logger: Logger instance.

    Returns:
        List of uploaded attachment URLs.
    """
    from perplexity_cli.utils.file_handler import load_attachments

    file_attachments = load_attachments(file_paths)
    logger.debug("Attachment loading complete: %s file(s) loaded", len(file_attachments))
    for attachment in file_attachments:
        logger.debug(
            "  - %s (%s, %s bytes base64)",
            redact_path(attachment.filename),
            attachment.content_type,
            len(attachment.data),
        )

    if not file_attachments:
        return []

    return _do_s3_upload(file_attachments, token, cookies, logger)


def _do_s3_upload(
    file_attachments: list[FileAttachment],
    token: str,
    cookies: dict[str, str] | None,
    logger: logging.Logger,
) -> list[str]:
    """Upload file attachments to S3.

    Args:
        file_attachments: List of loaded file attachment objects.
        token: Validated authentication token.
        cookies: Browser cookies.
        logger: Logger instance.

    Returns:
        List of uploaded attachment URLs.
    """
    from perplexity_cli.attachments import AttachmentUploader

    logger.debug("Starting S3 upload for attachments")
    uploader = AttachmentUploader(token=token, cookies=cookies)
    try:
        attachment_urls = run_async(uploader.upload_files(file_attachments))
    except AttachmentUploadError as e:
        click.echo(f"[ERROR] Failed to upload attachments: {e}", err=True)
        logger.error("Attachment upload failed: %s", e)
        raise SystemExit(1)

    logger.debug("S3 upload complete: %s file(s) uploaded", len(attachment_urls))
    for i, url in enumerate(attachment_urls, 1):
        logger.debug("  [%s] %s", i, redact_url(url))
    return attachment_urls


def get_query_formatter(output_format: str | None) -> tuple[str, Formatter]:
    """Resolve the configured formatter for the query command."""
    from perplexity_cli.formatting import get_formatter, list_formatters

    logger = get_logger()
    resolved_output_format = output_format or "rich"
    try:
        formatter = get_formatter(resolved_output_format)
    except ValueError as e:
        click.echo(f"[ERROR] {e}", err=True)
        available = ", ".join(list_formatters())
        click.echo(f"Available formats: {available}", err=True)
        logger.error("Invalid formatter: %s", resolved_output_format)
        raise SystemExit(1)

    return resolved_output_format, formatter


def build_final_query(query_text: str) -> str:
    """Apply any configured style prompt to the query text."""
    from perplexity_cli.utils.style_manager import StyleManager

    logger = get_logger()
    style = StyleManager().load_style()
    if not style:
        return query_text

    logger.debug("Applied style: %s", redact_text(style))
    return f"{query_text}\n\n{style}"


def render_complete_answer(answer_obj: Answer, render: RenderContext) -> None:
    """Render the non-streaming query result."""
    if render.options.output_format == "rich":
        render.formatter.render_complete(
            answer_obj,
            strip_references=render.options.strip_references,
        )
        return

    formatted_output = render.formatter.format_complete(
        answer_obj,
        strip_references=render.options.strip_references,
    )
    click.echo(formatted_output)


def _read_query_from_stdin(query_text: str) -> str:
    """Read query text from stdin if the sentinel value is provided.

    Args:
        query_text: The query string, or "-" to read from stdin.

    Returns:
        The resolved query text.
    """
    if query_text != "-":
        return query_text
    if sys.stdin.isatty():
        click.echo("Error: stdin is a terminal; pipe input or provide a query.", err=True)
        raise SystemExit(2)
    text = sys.stdin.read().strip()
    if not text:
        click.echo("Error: empty input from stdin.", err=True)
        raise SystemExit(2)
    return text


def _build_json_envelope(  # nosemgrep: boolean-flag-argument
    answer_obj: Answer, trace: TraceContext, include_schema: bool
) -> str:
    """Build the JSON envelope output for --json mode.

    Args:
        answer_obj: The answer object from the API.
        trace: Trace and timing context.
        include_schema: Whether to include JSON schema in output.

    Returns:
        JSON string ready for output.
    """
    from perplexity_cli.envelope import Meta, envelope_to_dict, success_envelope
    from perplexity_cli.utils.version import get_version

    result = {
        "answer": answer_obj.text,
        "references": [
            {"name": r.name, "url": r.url, "snippet": r.snippet} for r in answer_obj.references
        ],
    }
    effective_start = trace.start_time if trace.start_time is not None else time.monotonic()
    meta = Meta(
        duration_ms=int((time.monotonic() - effective_start) * 1000),
        version=get_version(),
        trace_id=trace.trace_id or "",
    )
    envelope = success_envelope(command=_QUERY_JSON_COMMAND, result=result, meta=meta)
    envelope_dict = envelope_to_dict(envelope, include_schema=include_schema)
    return json.dumps(envelope_dict, default=str) + "\n"


def _handle_query_exception(  # nosemgrep: boolean-flag-argument
    exc: Exception, ctx_obj: dict[str, object] | None, json_mode: bool
) -> None:
    """Dispatch query exceptions to the appropriate error handler.

    Args:
        exc: The exception to handle.
        ctx_obj: The Click context object dictionary.
        json_mode: Whether JSON output mode is active.
    """
    from perplexity_cli.error_handler import handle_error

    logger = get_logger()
    debug_mode: bool = bool((ctx_obj or {}).get("debug", False))

    if json_mode:
        handle_error(
            exc,
            command=_QUERY_JSON_COMMAND,
            json_mode=True,
        )

    if _try_dispatch_known_error(exc, logger, debug_mode):
        return

    _handle_fallback_error(exc, logger, debug_mode)


def _try_dispatch_known_error(  # nosemgrep: boolean-flag-argument
    exc: Exception, logger: logging.Logger, debug_mode: bool
) -> bool:
    """Attempt to handle a known error type.

    Args:
        exc: The exception to check.
        logger: Logger instance.
        debug_mode: Whether debug mode is active.

    Returns:
        True if the error was handled, False otherwise.
    """
    from perplexity_cli.utils.http_errors import handle_http_error, handle_network_error

    if isinstance(exc, PerplexityHTTPStatusError):
        handle_http_error(exc, logger, debug_mode=debug_mode)
        return True
    if isinstance(exc, PerplexityRequestError):
        handle_network_error(exc, logger, debug_mode=debug_mode)
        return True
    if isinstance(exc, UpstreamSchemaError):
        logger.error("Upstream schema error: %s", exc)
        click.echo(f"[ERROR] Upstream response format changed: {exc}", err=True)
        raise SystemExit(1)
    if isinstance(exc, (ConfigurationError, AttachmentError, AttachmentUploadError, ValueError)):
        logger.error("Value error: %s", exc)
        click.echo(f"[ERROR] Error: {exc}", err=True)
        raise SystemExit(1)
    return False


def _handle_fallback_error(  # nosemgrep: boolean-flag-argument
    exc: Exception, logger: logging.Logger, debug_mode: bool
) -> None:
    """Handle an unexpected error type.

    Args:
        exc: The exception.
        logger: Logger instance.
        debug_mode: Whether debug mode is active.
    """
    from perplexity_cli.utils.http_errors import handle_unexpected_cli_error

    handle_unexpected_cli_error(
        exc,
        logger,
        debug_mode=debug_mode,
        message_tuple=("[ERROR] An unexpected error occurred.", "Unexpected error", True),
    )


def _fetch_and_render(
    api: PerplexityAPI,
    query_input: QueryInput,
    render: RenderContext,
    trace: TraceContext,
) -> None:
    """Fetch a complete answer and render it.

    Args:
        api: The PerplexityAPI instance.
        query_input: Query text, attachment URLs, and model preference.
        render: Formatter and output options.
        trace: Trace and timing context.
    """
    logger = get_logger()
    logger.info("Fetching complete answer")
    answer_obj = api.get_complete_answer(
        query_input.query,
        extra_params=(query_input.attachment_urls, query_input.model_preference, query_input.request_params),
    )
    logger.debug(
        "Received answer: %s characters, %s references",
        len(answer_obj.text),
        len(answer_obj.references),
    )

    if render.options.json_mode:
        sys.stdout.write(
            _build_json_envelope(answer_obj, trace, render.options.include_schema),
        )
    else:
        render_complete_answer(answer_obj, render)


def _read_ctx_options(
    ctx_obj: dict[str, object] | None,
) -> tuple[bool, int | None, bool]:
    """Extract query options from the Click context object.

    Args:
        ctx_obj: The Click context object dictionary, or None.

    Returns:
        Tuple of (json_mode, timeout, include_schema).
    """
    opts: dict[str, object] = ctx_obj or {}
    json_val: object = opts.get("json", False)
    timeout_val: object = opts.get("timeout")
    schema_val: object = opts.get("schema", False)
    return (
        bool(json_val),
        int(timeout_val) if isinstance(timeout_val, int) else None,
        bool(schema_val),
    )


def parse_request_param_overrides(overrides: Iterable[str]) -> dict[str, str]:
    """Parse repeated ``key=value`` request parameter overrides.

    Args:
        overrides: Raw override strings from the CLI.

    Returns:
        Mapping of request parameter keys to values.

    Raises:
        ValueError: If any override is malformed or repeated.
    """
    parsed: dict[str, str] = {}
    for raw_override in overrides:
        key, value = _parse_request_param_override(raw_override)
        _check_for_duplicate_request_param(parsed, key)
        parsed[key] = value
    return parsed


def _parse_request_param_override(raw_override: str) -> tuple[str, str]:
    """Parse a single request parameter override."""
    key, separator, value = raw_override.partition("=")
    if not separator or not key or not value:
        raise ValueError("Request parameter overrides must use the form key=value")
    return key, value


def _check_for_duplicate_request_param(parsed: dict[str, str], key: str) -> None:
    """Reject duplicate request parameter override keys."""
    if key in parsed:
        raise ValueError(f"Duplicate request parameter override: {key}")


def run_query_command(
    ctx_obj: dict[str, object] | None,
    query_text: str,
    options: QueryOptions,
) -> None:
    """Execute the query command while keeping cli.py focused on wiring."""
    output_format = options.output_format
    strip_references = options.strip_references
    stream = options.stream
    attachments_str = options.attachments
    model_preference = options.model_preference
    request_param_overrides = options.request_param_overrides

    from perplexity_cli.api.endpoints import PerplexityAPI
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.auth.utils import load_token_optional
    from perplexity_cli.query_streaming import stream_query_response

    logger = get_logger()
    query_text = _read_query_from_stdin(query_text)
    json_mode, timeout, include_schema = _read_ctx_options(ctx_obj)

    trace = TraceContext(trace_id=str(uuid.uuid4()), start_time=time.monotonic())

    log_query_debug_context(query_text, output_format, stream)

    tm = TokenManager()
    token, cookies = load_token_optional(tm, logger)
    auth = AuthContext(token=token, cookies=cookies)
    attachment_urls = resolve_attachment_urls(query_text, attachments_str, auth)

    try:
        resolved_output_format, formatter = get_query_formatter(output_format)
        final_query = build_final_query(query_text)
        request_params = parse_request_param_overrides(request_param_overrides)

        query_input = QueryInput(
            query=final_query,
            attachment_urls=attachment_urls,
            model_preference=model_preference,
            request_params=request_params,
        )
        output_opts = OutputOptions(
            output_format=resolved_output_format,
            strip_references=strip_references,
            json_mode=json_mode,
            include_schema=include_schema,
        )
        render = RenderContext(formatter=formatter, options=output_opts)

        with PerplexityAPI(token, cookies, timeout=timeout) as api:
            if stream:
                logger.info("Streaming query response")
                stream_query_response(api, query_input, render, trace)
            else:
                _fetch_and_render(api, query_input, render, trace)

    except KeyboardInterrupt:
        _handle_keyboard_interrupt(json_mode, logger)

    except Exception as exc:
        _handle_query_exception(exc, ctx_obj, json_mode)


def _handle_keyboard_interrupt(  # nosemgrep: boolean-flag-argument
    json_mode: bool, logger: logging.Logger
) -> None:
    """Handle a keyboard interrupt during query execution.

    Args:
        json_mode: Whether JSON output mode is active.
        logger: Logger instance.
    """
    if json_mode:
        from perplexity_cli.error_handler import handle_error

        handle_error(
            KeyboardInterrupt(),
            command=_QUERY_JSON_COMMAND,
            json_mode=True,
        )
    logger.info("Query interrupted by user")
    click.echo("\n[ERROR] Query interrupted.", err=True)
    raise SystemExit(130)
