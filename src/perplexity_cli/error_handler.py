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


def _classify_exception(exc: BaseException) -> tuple[ErrorCode, str | None]:
    """Map an exception to an ErrorCode and optional fix suggestion."""
    if isinstance(exc, AuthenticationError):
        return ErrorCode.authentication_required, "Run `pxcli auth login` to authenticate."
    if isinstance(exc, RateLimitError):
        return ErrorCode.rate_limited, "Wait a moment and try again."
    if isinstance(exc, PerplexityHTTPStatusError):
        status = exc.response.status_code
        if status == 401:
            return ErrorCode.authentication_required, None
        if status == 403:
            return ErrorCode.permission_denied, None
        if status == 429:
            return ErrorCode.rate_limited, None
        if status >= 500:
            return ErrorCode.network_error, None
        return ErrorCode.network_error, None
    if isinstance(exc, PerplexityRequestError):
        return ErrorCode.network_error, "Check your internet connection."
    if isinstance(exc, ConfigurationError):
        return ErrorCode.configuration_error, None
    if isinstance(exc, UpstreamSchemaError):
        return ErrorCode.upstream_schema_error, None
    if isinstance(exc, AttachmentError):
        return ErrorCode.attachment_error, None
    if isinstance(exc, ValueError):
        return ErrorCode.validation_error, None
    return ErrorCode.internal_error, None


def handle_error(
    exc: BaseException,
    *,
    command: str,
    json_mode: bool = False,
    debug_mode: bool = False,
    include_schema: bool = False,
) -> NoReturn:
    """Handle an exception, outputting either JSON or human-readable error, then exit."""
    code, fix = _classify_exception(exc)
    exit_code = exit_code_for_exception(exc)

    if json_mode:
        env = error_envelope(command, code, str(exc), fix=fix)
        data = envelope_to_dict(env, include_schema=include_schema)
        sys.stdout.write(json.dumps(data, default=str) + "\n")
        sys.exit(exit_code)
    else:
        message = str(exc)
        click.echo(f"Error: {message}", err=True)
        if fix:
            click.echo(f"Fix: {fix}", err=True)
        sys.exit(exit_code)
