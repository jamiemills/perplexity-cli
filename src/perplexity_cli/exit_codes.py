"""Exit code constants and exception-to-exit-code mapping."""

from __future__ import annotations

from typing import Final

from perplexity_cli.utils.exceptions import (
    AttachmentError,
    AuthenticationError,
    ConfigurationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    RateLimitError,
    UpstreamSchemaError,
)

SUCCESS = 0
GENERAL_FAILURE = 1
USAGE_ERROR = 2
NOT_FOUND = 3
AUTH_REQUIRED = 4
CONFLICT = 5
TRANSIENT = 6
VALIDATION = 7
INTERRUPTED = 130


_RATE_LIMIT_STATUS: Final[int] = 429
_SERVER_ERROR_FLOOR: Final[int] = 500

_EXCEPTION_EXIT_CODE_TABLE: list[tuple[type, int]] = [
    (AuthenticationError, AUTH_REQUIRED),
    (RateLimitError, TRANSIENT),
    (PerplexityRequestError, TRANSIENT),
    (ConfigurationError, VALIDATION),
    (UpstreamSchemaError, VALIDATION),
    (AttachmentError, VALIDATION),
    (ValueError, GENERAL_FAILURE),
    (KeyboardInterrupt, INTERRUPTED),
]


def _exit_code_for_http_error(exc: PerplexityHTTPStatusError) -> int:
    """Determine exit code for an HTTP status error."""
    status = exc.response.status_code
    if status in (401, 403):
        return AUTH_REQUIRED
    if status == _RATE_LIMIT_STATUS or status >= _SERVER_ERROR_FLOOR:
        return TRANSIENT
    return GENERAL_FAILURE


def exit_code_for_exception(exc: BaseException) -> int:
    """Map an exception to the appropriate CLI exit code."""
    if isinstance(exc, PerplexityHTTPStatusError):
        return _exit_code_for_http_error(exc)
    for exc_type, code in _EXCEPTION_EXIT_CODE_TABLE:
        if isinstance(exc, exc_type):
            return code
    return GENERAL_FAILURE


def format_exit_codes_help() -> str:
    """Return a formatted text block listing all exit codes and their meanings."""
    return (
        "Exit codes:\n"
        "  0    Success\n"
        "  1    General failure\n"
        "  2    Usage error\n"
        "  3    Not found\n"
        "  4    Authentication required\n"
        "  5    Conflict\n"
        "  6    Transient error (retry may help)\n"
        "  7    Validation error\n"
        "  130  Interrupted (Ctrl+C)\n"
    )
