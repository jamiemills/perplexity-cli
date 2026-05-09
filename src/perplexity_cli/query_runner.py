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
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from perplexity_cli.api.models import Answer
    from perplexity_cli.formatting.base import Formatter

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


def log_query_debug_context(
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
        logger.debug(f"Hostname: {hostname}")
    except OSError:
        pass

    logger.debug(f"Platform: {sys.platform}")
    logger.debug(f"Python version: {sys.version.split()[0]}")
    logger.debug(f"Python executable: {sys.executable}")

    exec_env = "unknown"
    if hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix:
        exec_env = "virtualenv"
    if "VIRTUAL_ENV" in os.environ:
        exec_env = "venv"
    if "UV_ACTIVE" in os.environ or "UVXENV" in os.environ:
        exec_env = "uvx"

    logger.debug(f"Execution environment: {exec_env}")

    token_path = get_config_paths().token_path
    logger.debug(f"Token path: {redact_path(token_path)}")
    logger.debug(f"Token exists: {token_path.exists()}")
    logger.debug(f"Cookie storage enabled: {get_save_cookies_enabled()}")
    logger.debug(
        f"Query command invoked: query={redact_text(query_text)}, "
        f"format={output_format}, stream={stream}"
    )


def resolve_attachment_urls(
    query_text: str,
    attachments_str: tuple[str, ...],
    token: str | None,
    cookies: dict[str, str] | None,
) -> list[str]:
    """Load local attachments and upload them when needed."""
    from perplexity_cli.attachments import AttachmentUploader
    from perplexity_cli.utils.file_handler import load_attachments, resolve_file_arguments

    logger = get_logger()
    attachment_list = list(attachments_str)
    if not attachment_list and "/" not in query_text and "\\" not in query_text:
        return []

    try:
        file_paths = resolve_file_arguments(
            [query_text],
            attach_args=attachment_list if attachment_list else None,
        )
        if not file_paths:
            return []

        logger.debug(f"Resolving attachments: found {len(file_paths)} file(s)")

        if not token:
            click.echo("[ERROR] File attachments require authentication.", err=True)
            click.echo("\nPlease authenticate first with: pxcli auth", err=True)
            logger.error("Attachment upload attempted without authentication")
            sys.exit(1)

        file_attachments = load_attachments(file_paths)
        logger.debug(f"Attachment loading complete: {len(file_attachments)} file(s) loaded")
        for attachment in file_attachments:
            logger.debug(
                f"  - {redact_path(attachment.filename)} ({attachment.content_type}, "
                f"{len(attachment.data)} bytes base64)"
            )

        if not file_attachments:
            return []

        logger.debug("Starting S3 upload for attachments")
        uploader = AttachmentUploader(token=token, cookies=cookies)
        try:
            attachment_urls = run_async(uploader.upload_files(file_attachments))
        except AttachmentUploadError as e:
            click.echo(f"[ERROR] Failed to upload attachments: {e}", err=True)
            logger.error(f"Attachment upload failed: {e}")
            sys.exit(1)

        logger.debug(f"S3 upload complete: {len(attachment_urls)} file(s) uploaded")
        for i, url in enumerate(attachment_urls, 1):
            logger.debug(f"  [{i}] {redact_url(url)}")
        return attachment_urls

    except (FileNotFoundError, AttachmentError, ValueError) as e:
        click.echo(f"[ERROR] Failed to load attachments: {e}", err=True)
        logger.error(f"Attachment loading failed: {e}")
        sys.exit(1)


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
        logger.error(f"Invalid formatter: {resolved_output_format}")
        sys.exit(1)

    return resolved_output_format, formatter


def build_final_query(query_text: str) -> str:
    """Apply any configured style prompt to the query text."""
    from perplexity_cli.utils.style_manager import StyleManager

    logger = get_logger()
    style = StyleManager().load_style()
    if not style:
        return query_text

    logger.debug(f"Applied style: {redact_text(style)}")
    return f"{query_text}\n\n{style}"


def render_complete_answer(
    answer_obj: Answer, formatter: Formatter, output_format: str, strip_references: bool
) -> None:
    """Render the non-streaming query result."""
    if output_format == "rich":
        formatter.render_complete(answer_obj, strip_references=strip_references)
        return

    formatted_output = formatter.format_complete(answer_obj, strip_references=strip_references)
    click.echo(formatted_output)


def run_query_command(
    ctx_obj: dict | None,
    query_text: str,
    output_format: str | None,
    strip_references: bool,
    stream: bool,
    attachments_str: tuple[str, ...],
) -> None:
    """Execute the query command while keeping cli.py focused on wiring."""
    from perplexity_cli.api.endpoints import PerplexityAPI
    from perplexity_cli.api.streaming import stream_query_response
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.auth.utils import load_token_optional
    from perplexity_cli.error_handler import handle_error
    from perplexity_cli.utils.http_errors import (
        handle_http_error,
        handle_network_error,
        handle_unexpected_cli_error,
    )

    logger = get_logger()

    # Stdin support: if query_text is "-", read from stdin.
    if query_text == "-":
        if sys.stdin.isatty():
            click.echo("Error: stdin is a terminal; pipe input or provide a query.", err=True)
            sys.exit(2)
        query_text = sys.stdin.read().strip()
        if not query_text:
            click.echo("Error: empty input from stdin.", err=True)
            sys.exit(2)

    # Read json_mode, timeout, and include_schema from ctx_obj.
    json_mode = (ctx_obj or {}).get("json", False)
    timeout = (ctx_obj or {}).get("timeout")
    include_schema = (ctx_obj or {}).get("schema", False)

    # Generate trace_id and timing.
    trace_id = str(uuid.uuid4())
    start_time = time.monotonic()

    log_query_debug_context(query_text, output_format, stream)

    tm = TokenManager()
    token, cookies = load_token_optional(tm, logger)
    attachment_urls = resolve_attachment_urls(query_text, attachments_str, token, cookies)

    try:
        resolved_output_format, formatter = get_query_formatter(output_format)
        final_query = build_final_query(query_text)

        # Build API kwargs, including timeout if set.
        api_kwargs: dict = {"token": token, "cookies": cookies}
        if timeout is not None:
            api_kwargs["timeout"] = timeout

        with PerplexityAPI(**api_kwargs) as api:
            if stream:
                logger.info("Streaming query response")
                stream_query_response(
                    api,
                    final_query,
                    formatter,
                    resolved_output_format,
                    strip_references,
                    attachments=attachment_urls,
                    json_mode=json_mode,
                    trace_id=trace_id,
                    start_time=start_time,
                )
                return

            logger.info("Fetching complete answer")
            answer_obj = api.get_complete_answer(final_query, attachments=attachment_urls)
            logger.debug(
                f"Received answer: {len(answer_obj.text)} characters, "
                f"{len(answer_obj.references)} references"
            )

            if json_mode:
                # Envelope output for --json mode (non-streaming).
                from perplexity_cli.envelope import Meta, envelope_to_dict, success_envelope
                from perplexity_cli.utils.version import get_version

                result = {
                    "answer": answer_obj.text,
                    "references": [
                        {"name": r.name, "url": r.url, "snippet": r.snippet}
                        for r in answer_obj.references
                    ],
                }
                meta = Meta(
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                    version=get_version(),
                    trace_id=trace_id,
                )
                envelope = success_envelope(
                    command="pxcli query --json",
                    result=result,
                    meta=meta,
                )
                data = envelope_to_dict(envelope, include_schema=include_schema)
                sys.stdout.write(json.dumps(data, default=str) + "\n")
            else:
                render_complete_answer(
                    answer_obj,
                    formatter,
                    resolved_output_format,
                    strip_references,
                )

    except KeyboardInterrupt:
        if json_mode:
            handle_error(
                KeyboardInterrupt(),
                command="pxcli query --json",
                json_mode=True,
                debug_mode=(ctx_obj or {}).get("debug", False),
            )
        logger.info("Query interrupted by user")
        click.echo("\n[ERROR] Query interrupted.", err=True)
        sys.exit(130)

    except Exception as exc:
        debug_mode = (ctx_obj or {}).get("debug", False)
        if json_mode:
            handle_error(
                exc,
                command="pxcli query --json",
                json_mode=True,
                debug_mode=debug_mode,
            )

        # Non-json error handling (existing behaviour).
        if isinstance(exc, PerplexityHTTPStatusError):
            handle_http_error(exc, logger, debug_mode=debug_mode)
        elif isinstance(exc, PerplexityRequestError):
            handle_network_error(exc, logger, debug_mode=debug_mode)
        elif isinstance(exc, UpstreamSchemaError):
            logger.error(f"Upstream schema error: {exc}")
            click.echo(f"[ERROR] Upstream response format changed: {exc}", err=True)
            sys.exit(1)
        elif isinstance(
            exc, (ConfigurationError, AttachmentError, AttachmentUploadError, ValueError)
        ):
            logger.error(f"Value error: {exc}")
            click.echo(f"[ERROR] Error: {exc}", err=True)
            sys.exit(1)
        else:
            handle_unexpected_cli_error(
                exc,
                logger,
                debug_mode=debug_mode,
                user_message="[ERROR] An unexpected error occurred.",
                log_message="Unexpected error",
                include_debug_hint=True,
            )
