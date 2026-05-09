"""Exit code constants and exception-to-exit-code mapping."""

from __future__ import annotations

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


def exit_code_for_exception(exc: BaseException) -> int:
    """Map an exception to the appropriate CLI exit code."""
    if isinstance(exc, AuthenticationError):
        return AUTH_REQUIRED
    if isinstance(exc, RateLimitError):
        return TRANSIENT
    if isinstance(exc, PerplexityHTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return AUTH_REQUIRED
        if status == 429 or status >= 500:
            return TRANSIENT
        return GENERAL_FAILURE
    if isinstance(exc, PerplexityRequestError):
        return TRANSIENT
    if isinstance(exc, (ConfigurationError, UpstreamSchemaError, AttachmentError)):
        return VALIDATION
    if isinstance(exc, ValueError):
        return GENERAL_FAILURE
    if isinstance(exc, KeyboardInterrupt):
        return INTERRUPTED
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
