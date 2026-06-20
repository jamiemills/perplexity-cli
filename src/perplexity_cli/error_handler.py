"""Centralised error handling for both JSON and human modes."""

from __future__ import annotations

import json
import sys
from typing import NoReturn

import click

from perplexity_cli.envelope import ErrorCode, envelope_to_dict, error_envelope
from perplexity_cli.exit_codes import exit_code_for_exception
from perplexity_cli.utils.exceptions import (
    AttachmentError,
    AuthenticationError,
    ConfigurationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    RateLimitError,
    UpstreamSchemaError,
)

_HTTP_STATUS_TO_ERROR: list[tuple[object, ErrorCode]] = [
    (401, ErrorCode.authentication_required),
    (403, ErrorCode.permission_denied),
    (429, ErrorCode.rate_limited),
]


def _classify_http_status_error(exc: PerplexityHTTPStatusError) -> tuple[ErrorCode, str | None]:
    """Classify an HTTP status error into an error code and fix suggestion."""
    status = exc.response.status_code
    for code_val, error_code in _HTTP_STATUS_TO_ERROR:
        if status == code_val:
            return error_code, None
    return ErrorCode.network_error, None


_EXCEPTION_CLASSIFY_TABLE: list[tuple[type, ErrorCode, str | None]] = [
    (
        AuthenticationError,
        ErrorCode.authentication_required,
        "Run `pxcli auth login` to authenticate.",
    ),
    (RateLimitError, ErrorCode.rate_limited, "Wait a moment and try again."),
    (PerplexityRequestError, ErrorCode.network_error, "Check your internet connection."),
    (ConfigurationError, ErrorCode.configuration_error, None),
    (UpstreamSchemaError, ErrorCode.upstream_schema_error, None),
    (AttachmentError, ErrorCode.attachment_error, None),
    (ValueError, ErrorCode.validation_error, None),
]


def _classify_exception(exc: BaseException) -> tuple[ErrorCode, str | None]:
    """Map an exception to an ErrorCode and optional fix suggestion."""
    if isinstance(exc, PerplexityHTTPStatusError):
        return _classify_http_status_error(exc)
    for exc_type, error_code, fix in _EXCEPTION_CLASSIFY_TABLE:
        if isinstance(exc, exc_type):
            return error_code, fix
    return ErrorCode.internal_error, None


def handle_error(  # nosemgrep: too-many-parameters, boolean-flag-argument
    exc: BaseException,
    *,
    command: str,
    json_mode: bool = False,
    debug_mode: bool = False,
    include_schema: bool = False,
) -> NoReturn:
    """Handle an exception, outputting either JSON or human-readable error, then exit."""
    del debug_mode
    code, fix = _classify_exception(exc)
    exit_code = exit_code_for_exception(exc)

    if json_mode:
        env = error_envelope(command, code, str(exc), fix=fix)
        envelope_dict = envelope_to_dict(env, include_schema=include_schema)
        sys.stdout.write(json.dumps(envelope_dict, default=str) + "\n")
        sys.exit(exit_code)
    else:
        message = str(exc)
        click.echo(f"Error: {message}", err=True)
        if fix:
            click.echo(f"Fix: {fix}", err=True)
        sys.exit(exit_code)
