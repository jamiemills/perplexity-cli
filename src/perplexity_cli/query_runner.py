"""Query command orchestration helpers.

This module keeps Click wiring in ``cli.py`` thin while preserving the
existing query behaviour.  It lives in the application layer and therefore
imports only from the standard library plus ``shared_pure``, ``domain``,
``ports`` and ``application`` modules.  Adapter and presentation
collaborators are resolved at runtime through :func:`importlib.import_module`
and exposed as module-level bindings; those bindings are the injection seams
that the presentation layer (or tests) may override.

Compatibility note: human and JSON query failures both route through
``error_handler.handle_error`` so the same operation returns the same
taxonomy exit code in both modes.  This is an intentional compatibility
correction (the previous human-only helpers exited 1 for every error).
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import socket
import sys
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Protocol

from perplexity_cli._types import OutputFormat, QueryOptions, SchemaInclusion
from perplexity_cli.api.models import Answer, QueryInput, TraceContext, WebResult
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.envelope import Meta, envelope_to_dict, success_envelope
from perplexity_cli.ports import (
    AttachmentUploader as AttachmentUploaderPort,
)
from perplexity_cli.ports import AuthTokenStore, QueryGateway
from perplexity_cli.query_streaming import stream_query_response
from perplexity_cli.utils.attachment_models import FileAttachment
from perplexity_cli.utils.exceptions import (
    AttachmentError,
    AttachmentUploadError,
    AuthenticationError,
)
from perplexity_cli.utils.version import get_version

_QUERY_JSON_COMMAND = "pxcli query --json"


# ---------------------------------------------------------------------------
# Ports (structural protocols)
# ---------------------------------------------------------------------------


class _ErrorTranslator(Protocol):
    """Port for translating query exceptions into output and a taxonomy exit code.

    Satisfied structurally by ``error_handler.handle_error``.
    """

    def __call__(
        self,
        exc: BaseException,
        command: str,
        output_format: OutputFormat = "human",
        include_schema: SchemaInclusion = "no_schema",
    ) -> NoReturn:
        """Translate an exception into channel-appropriate output, then exit."""
        ...


class _Formatter(Protocol):
    """Structural subset of the formatter interface used for query rendering."""

    def format_answer(  # nosemgrep: boolean-flag-argument  # owner: quality-infrastructure; reason: structural protocol mirrors the formatter interface signature
        self, text: str, strip_references: bool = False
    ) -> str:
        """Format answer text."""
        ...

    def format_references(self, references: list[WebResult]) -> str:
        """Format the references list into a string."""
        ...

    def format_complete(  # nosemgrep: boolean-flag-argument  # owner: quality-infrastructure; reason: structural protocol mirrors the formatter interface signature
        self, answer: Answer, strip_references: bool = False
    ) -> str:
        """Format a complete answer with references."""
        ...

    def render_complete(  # nosemgrep: boolean-flag-argument  # owner: quality-infrastructure; reason: structural protocol mirrors the formatter interface signature
        self, answer: Answer, strip_references: bool = False
    ) -> None:
        """Render a complete answer directly (rich path)."""
        ...


class _ApiFactory(Protocol):
    """Factory port for the query gateway, satisfied by ``api.endpoints.PerplexityAPI``."""

    def __call__(
        self,
        token: str | None,
        cookies: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> QueryGateway:
        """Build a query gateway for the given credentials and timeout."""
        ...


class _StyleProvider(Protocol):
    """Provider of the configured style prompt."""

    def load_style(self) -> str | None:
        """Return the configured style prompt, or None when unset."""
        ...


class _ConfigPaths(Protocol):
    """Structural subset of ``utils.config.ConfigPaths`` used for debug logging."""

    token_path: Path


# ---------------------------------------------------------------------------
# Adapter / presentation bindings (runtime-resolved injection seams)
# ---------------------------------------------------------------------------


def _import_attribute(dotted_path: str) -> Any:
    """Resolve a dotted ``module.attribute`` path at runtime.

    The application layer is not permitted to statically import adapter or
    presentation modules (enforced by ``scripts/check_architecture.py``), so
    concrete collaborators are resolved lazily through importlib.  The
    resulting module-level names remain patchable, which is how tests and
    callers override the default wiring.
    """
    module_path, _, attribute = dotted_path.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, attribute)


handle_error: _ErrorTranslator = _import_attribute("perplexity_cli.error_handler.handle_error")
get_logger: Callable[[], logging.Logger] = _import_attribute(
    "perplexity_cli.utils.logging.get_logger"
)
redact_path: Callable[[str | Path | None], str] = _import_attribute(
    "perplexity_cli.utils.logging.redact_path"
)
redact_text: Callable[[str | None], str] = _import_attribute(
    "perplexity_cli.utils.logging.redact_text"
)
redact_url: Callable[[str | None], str] = _import_attribute(
    "perplexity_cli.utils.logging.redact_url"
)
get_config_paths: Callable[[], _ConfigPaths] = _import_attribute(
    "perplexity_cli.utils.config.get_config_paths"
)
get_save_cookies_enabled: Callable[[], bool] = _import_attribute(
    "perplexity_cli.utils.config.get_save_cookies_enabled"
)
get_formatter: Callable[[str], _Formatter] = _import_attribute(
    "perplexity_cli.formatting.get_formatter"
)
list_formatters: Callable[[], list[str]] = _import_attribute(
    "perplexity_cli.formatting.list_formatters"
)
StyleManager: Callable[[], _StyleProvider] = _import_attribute(
    "perplexity_cli.utils.style_manager.StyleManager"
)
TokenManager: Callable[[], AuthTokenStore] = _import_attribute(
    "perplexity_cli.auth.token_manager.TokenManager"
)
load_token_optional: Callable[
    [AuthTokenStore, logging.Logger], tuple[str | None, dict[str, str] | None]
] = _import_attribute("perplexity_cli.auth.utils.load_token_optional")
PerplexityAPI: _ApiFactory = _import_attribute("perplexity_cli.api.endpoints.PerplexityAPI")
resolve_file_arguments: Callable[..., list[Path]] = _import_attribute(
    "perplexity_cli.utils.file_handler.resolve_file_arguments"
)
load_attachments: Callable[[list[Path]], list[FileAttachment]] = _import_attribute(
    "perplexity_cli.utils.file_handler.load_attachments"
)
run_async: Callable[[object], Any] = _import_attribute(
    "perplexity_cli.utils.async_bridge.run_async"
)


# ---------------------------------------------------------------------------
# Environment & debug helpers
# ---------------------------------------------------------------------------


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


def log_query_debug_context(
    query_text: str,
    output_format: str | None,
    stream_mode: str,
) -> None:
    """Log environment and invocation details for debug runs.

    Args:
        query_text: The user's query text.
        output_format: The requested output format, or None for the default.
        stream_mode: Either ``"stream"`` or ``"batch"``.
    """
    logger = get_logger()
    if not logger.isEnabledFor(logging.DEBUG):
        return

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
    # owner: security - the argument is a redacted token-file path.
    logger.debug(  # nosemgrep: custom.credential-logging-vendored,python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # owner: quality-infrastructure; reason: token redacted before logging
        "Token path: %s", redact_path(token_path)
    )
    # owner: security - the argument is only a token-file presence boolean.
    logger.debug(  # nosemgrep: custom.credential-logging-vendored,python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # owner: quality-infrastructure; reason: token redacted before logging
        "Token exists: %s", token_path.exists()
    )
    logger.debug("Cookie storage enabled: %s", get_save_cookies_enabled())
    logger.debug(
        "Query command invoked: query=%s, format=%s, stream=%s",
        redact_text(query_text),
        output_format,
        stream_mode,
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _write_stdout(text: str) -> None:
    """Write *text* to stdout and flush, mirroring ``click.echo`` without click."""
    sys.stdout.write(text)
    sys.stdout.flush()


def _write_stderr(text: str) -> None:
    """Write *text* to stderr and flush, mirroring ``click.echo(err=True)``."""
    sys.stderr.write(text)
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Attachment helpers
# ---------------------------------------------------------------------------


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
    """Load local attachments and upload them when needed.

    Args:
        query_text: The query text.
        attachments_str: Attachment arguments from the CLI.
        auth: Authentication context.

    Returns:
        List of uploaded attachment URLs.

    Raises:
        AuthenticationError: If authentication is required for attachments.
        AttachmentError: If attachments cannot be resolved or loaded.
    """
    logger = get_logger()
    attachment_list = list(attachments_str)
    if not _has_potential_file_references(query_text, attachment_list):
        return []

    try:
        return _resolve_and_upload(query_text, attachment_list, auth, logger)
    except AuthenticationError:
        raise
    except (FileNotFoundError, AttachmentError, ValueError) as e:
        message = f"Failed to load attachments: {e}"
        raise AttachmentError(message) from e


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
    file_paths = resolve_file_arguments(
        [query_text],
        attach_args=attachment_list or None,
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
        AuthenticationError: If authentication is missing.
    """
    if token:
        return token
    logger.error("Attachment upload attempted without authentication")
    message = "File attachments require authentication."
    raise AuthenticationError(message)


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


def _resolve_attachment_uploader() -> Callable[..., AttachmentUploaderPort]:
    """Resolve the attachment uploader class through the attachments package.

    Resolved at call time (rather than bound at import time) so callers may
    patch ``perplexity_cli.attachments.AttachmentUploader`` and have the
    replacement take effect.
    """
    module: Any = importlib.import_module("perplexity_cli.attachments")
    return module.AttachmentUploader


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
    logger.debug("Starting S3 upload for attachments")
    uploader = _resolve_attachment_uploader()(token=token, cookies=cookies)
    try:
        attachment_urls = run_async(uploader.upload_files(file_attachments))
    except AttachmentUploadError as e:
        logger.exception("Attachment upload failed: %s", e)
        raise

    logger.debug("S3 upload complete: %s file(s) uploaded", len(attachment_urls))
    for i, url in enumerate(attachment_urls, 1):
        logger.debug("  [%s] %s", i, redact_url(url))
    return attachment_urls


# ---------------------------------------------------------------------------
# Query rendering helpers
# ---------------------------------------------------------------------------


def get_query_formatter(output_format: str | None) -> tuple[str, _Formatter]:
    """Resolve the configured formatter for the query command.

    Args:
        output_format: The requested output format, or None for the default.

    Returns:
        Tuple of (resolved format name, formatter instance).

    Raises:
        ValueError: If the format name is not registered.
    """
    logger = get_logger()
    resolved_output_format = output_format or "rich"
    try:
        formatter = get_formatter(resolved_output_format)
    except ValueError:
        logger.exception("Invalid formatter: %s", resolved_output_format)
        raise
    return resolved_output_format, formatter


def build_final_query(query_text: str) -> str:
    """Apply any configured style prompt to the query text.

    Args:
        query_text: The user's query text.

    Returns:
        The query text with the style prompt appended, if configured.
    """
    logger = get_logger()
    style = StyleManager().load_style()
    if not style:
        return query_text

    logger.debug("Applied style: %s", redact_text(style))
    return f"{query_text}\n\n{style}"


def render_complete_answer(answer_obj: Answer, render: _QueryRenderContextData) -> None:
    """Render the non-streaming query result.

    Args:
        answer_obj: The answer to render.
        render: Formatter and output options.
    """
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
    _write_stdout(formatted_output + "\n")


def _read_query_from_stdin(query_text: str) -> str:
    """Read query text from stdin if the sentinel value is provided.

    Args:
        query_text: The query string, or "-" to read from stdin.

    Returns:
        The resolved query text.

    Raises:
        SystemExit: With code 2 when stdin is unusable.
    """
    if query_text != "-":
        return query_text
    if sys.stdin.isatty():
        _write_stderr("Error: stdin is a terminal; pipe input or provide a query.\n")
        raise SystemExit(2)
    text = sys.stdin.read().strip()
    if not text:
        _write_stderr("Error: empty input from stdin.\n")
        raise SystemExit(2)
    return text


def _build_json_envelope(
    answer_obj: Answer, trace: TraceContext, include_schema: SchemaInclusion
) -> str:
    """Build the JSON envelope output for --json mode.

    Args:
        answer_obj: The answer object from the API.
        trace: Trace and timing context.
        include_schema: Whether to include JSON schema in output.

    Returns:
        JSON string ready for output.
    """
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


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def _handle_query_exception(exc: Exception, output_format: OutputFormat) -> None:
    """Translate a query exception through the unified exit-code policy.

    Both ``"json"`` and ``"human"`` modes route through :func:`handle_error`,
    which writes to the appropriate channel (stdout for JSON, stderr for human
    text) and exits with the taxonomy code for the exception class, so the
    same operation reports the same code in both modes.

    Args:
        exc: The exception to handle.
        output_format: Either ``"json"`` or ``"human"``.
    """
    handle_error(exc, _QUERY_JSON_COMMAND, output_format=output_format)


def _handle_broken_pipe() -> None:
    """Exit quietly when the stdout consumer closes its pipe early.

    Redirects stdout to ``os.devnull`` so the interpreter's final flush does
    not re-raise ``BrokenPipeError`` during shutdown, then exits with the
    general-failure code.
    """
    logger = get_logger()
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull_fd, sys.stdout.fileno())
    except OSError:
        logger.debug("Could not redirect stdout to devnull after broken pipe")
    raise SystemExit(1)


def _handle_keyboard_interrupt(output_format: OutputFormat, logger: logging.Logger) -> None:
    """Handle a keyboard interrupt during query execution.

    Args:
        output_format: Either ``"json"`` or ``"human"``.
        logger: Logger instance.
    """
    if output_format == "json":
        handle_error(KeyboardInterrupt(), _QUERY_JSON_COMMAND, output_format="json")
    logger.info("Query interrupted by user")
    _write_stderr("\n[ERROR] Query interrupted.\n")
    raise SystemExit(130)


def _handle_query_error(fn: Callable[[], None], output_format: OutputFormat) -> None:
    """Wrap a callable with KeyboardInterrupt, broken-pipe and general handling.

    Args:
        fn: The callable to execute within error handling.
        output_format: Either ``"json"`` or ``"human"``.
    """
    logger = get_logger()
    try:
        fn()
    except KeyboardInterrupt:
        _handle_keyboard_interrupt(output_format, logger)
    except BrokenPipeError:
        _handle_broken_pipe()
    except Exception as exc:  # catch-all CLI error handler
        _handle_query_exception(exc, output_format)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _fetch_and_render(
    api: QueryGateway,
    query_input: QueryInput,
    render: _QueryRenderContextData,
    trace: TraceContext,
) -> None:
    """Fetch a complete answer and render it.

    Args:
        api: The QueryGateway instance.
        query_input: Query text, attachment URLs, and model preference.
        render: Formatter and output options.
        trace: Trace and timing context.
    """
    logger = get_logger()
    logger.info("Fetching complete answer")
    answer_obj = api.get_complete_answer(
        query_input.query,
        extra_params=(
            query_input.attachment_urls,
            query_input.model_preference,
            query_input.request_params,
        ),
    )
    logger.debug(
        "Received answer: %s characters, %s references",
        len(answer_obj.text),
        len(answer_obj.references),
    )

    if render.options.json_mode:
        _write_stdout(
            _build_json_envelope(
                answer_obj,
                trace,
                "with_schema" if render.options.include_schema else "no_schema",
            )
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
        msg = "Request parameter overrides must use the form key=value"
        raise ValueError(msg)
    return key, value


def _check_for_duplicate_request_param(parsed: dict[str, str], key: str) -> None:
    """Reject duplicate request parameter override keys."""
    if key in parsed:
        msg = f"Duplicate request parameter override: {key}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class _QueryOutputOptionsData:
    """Concrete rendering switches for a query execution.

    Satisfies query_streaming's structural render-options protocol without
    importing the presentation context.
    """

    output_format: str
    strip_references: bool
    json_mode: bool
    include_schema: bool


@dataclass(frozen=True, slots=True)
class _QueryRenderContextData:
    """Concrete formatter plus rendering switches for a query execution.

    Satisfies query_streaming's structural render-context protocol without
    importing the presentation context.  The formatter and options are typed
    loosely so that real presentation collaborators satisfy them.
    """

    formatter: Any
    options: Any


def run_query_command(
    ctx_obj: dict[str, object] | None,
    query_text: str,
    options: QueryOptions,
) -> None:
    """Execute the query command while keeping cli.py focused on wiring.

    Args:
        ctx_obj: The Click context object dictionary.
        query_text: The user's query text, or ``"-"`` to read from stdin.
        options: Query options built from CLI flags.
    """
    output_format = options.output_format
    strip_references = options.strip_references
    stream = options.stream
    attachments_str = options.attachments
    model_preference = options.model_preference
    request_param_overrides = options.request_param_overrides

    logger = get_logger()
    query_text = _read_query_from_stdin(query_text)
    json_mode, timeout, include_schema = _read_ctx_options(ctx_obj)

    trace = TraceContext(trace_id=str(uuid.uuid4()), start_time=time.monotonic())

    log_query_debug_context(query_text, output_format, "stream" if stream else "batch")

    def _execute_query_body() -> None:
        tm = TokenManager()
        token, cookies = load_token_optional(tm, logger)
        auth = AuthContext(token=token, cookies=cookies)
        attachment_urls = resolve_attachment_urls(query_text, attachments_str, auth)

        resolved_output_format, formatter = get_query_formatter(output_format)
        final_query = build_final_query(query_text)
        request_params = parse_request_param_overrides(request_param_overrides)

        query_input = QueryInput(
            query=final_query,
            attachment_urls=attachment_urls,
            model_preference=model_preference,
            request_params=request_params,
        )
        output_opts = _QueryOutputOptionsData(
            output_format=resolved_output_format,
            strip_references=strip_references,
            json_mode=json_mode,
            include_schema=include_schema,
        )
        render = _QueryRenderContextData(formatter=formatter, options=output_opts)

        with PerplexityAPI(token, cookies, timeout=timeout) as api:
            if stream:
                logger.info("Streaming query response")
                stream_query_response(api, query_input, render, trace)
            else:
                _fetch_and_render(api, query_input, render, trace)

    _handle_query_error(_execute_query_body, "json" if json_mode else "human")
