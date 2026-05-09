"""Query command orchestration helpers.

This module keeps Click wiring in ``cli.py`` thin while preserving the
existing query behaviour.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import click

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

    from perplexity_cli.utils.config import get_save_cookies_enabled

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

    token_path = Path.home() / ".config" / "perplexity-cli" / "token.json"
    logger.debug(f"Token path: {redact_path(token_path)}")
    logger.debug(f"Token exists: {token_path.exists()}")
    logger.debug(f"Cookie storage enabled: {get_save_cookies_enabled()}")
    logger.debug(
        f"Query command invoked: query={redact_text(query_text)}, format={output_format}, stream={stream}"
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
            attachment_urls = asyncio.run(uploader.upload_files(file_attachments))
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


def get_query_formatter(output_format: str | None):
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
    answer_obj, formatter, output_format: str, strip_references: bool
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
    from perplexity_cli.utils.http_errors import (
        handle_http_error,
        handle_network_error,
        handle_unexpected_cli_error,
    )

    logger = get_logger()
    log_query_debug_context(query_text, output_format, stream)

    tm = TokenManager()
    token, cookies = load_token_optional(tm, logger)
    attachment_urls = resolve_attachment_urls(query_text, attachments_str, token, cookies)

    try:
        resolved_output_format, formatter = get_query_formatter(output_format)
        final_query = build_final_query(query_text)

        with PerplexityAPI(token=token, cookies=cookies) as api:
            if stream:
                logger.info("Streaming query response")
                stream_query_response(
                    api,
                    final_query,
                    formatter,
                    resolved_output_format,
                    strip_references,
                    attachments=attachment_urls,
                )
                return

            logger.info("Fetching complete answer")
            answer_obj = api.get_complete_answer(final_query, attachments=attachment_urls)
            logger.debug(
                f"Received answer: {len(answer_obj.text)} characters, {len(answer_obj.references)} references"
            )
            render_complete_answer(
                answer_obj,
                formatter,
                resolved_output_format,
                strip_references,
            )

    except PerplexityHTTPStatusError as e:
        debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
        handle_http_error(e, logger, debug_mode=debug_mode)

    except PerplexityRequestError as e:
        debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
        handle_network_error(e, logger, debug_mode=debug_mode)

    except UpstreamSchemaError as e:
        logger.error(f"Upstream schema error: {e}")
        click.echo(f"[ERROR] Upstream response format changed: {e}", err=True)
        sys.exit(1)

    except (ConfigurationError, AttachmentError, AttachmentUploadError, ValueError) as e:
        logger.error(f"Value error: {e}")
        click.echo(f"[ERROR] Error: {e}", err=True)
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Query interrupted by user")
        click.echo("\n[ERROR] Query interrupted.", err=True)
        sys.exit(130)

    except Exception as e:
        debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
        handle_unexpected_cli_error(
            e,
            logger,
            debug_mode=debug_mode,
            user_message="[ERROR] An unexpected error occurred.",
            log_message="Unexpected error",
            include_debug_hint=True,
        )
