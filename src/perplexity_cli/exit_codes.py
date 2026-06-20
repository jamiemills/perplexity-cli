"""Exit code constants and exception-to-exit-code mapping."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import dataclass
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

HTTP_STATUS_UNAUTHORIZED: Final[int] = 401
HTTP_STATUS_FORBIDDEN: Final[int] = 403
HTTP_STATUS_RATE_LIMITED: Final[int] = 429
HTTP_STATUS_SERVER_ERROR_FLOOR: Final[int] = 500

HTTP_STATUS_UNAUTHORIZED: Final[int] = 401
HTTP_STATUS_FORBIDDEN: Final[int] = 403
HTTP_STATUS_RATE_LIMITED: Final[int] = 429
HTTP_STATUS_SERVER_ERROR_FLOOR: Final[int] = 500



@dataclass(frozen=True, slots=True)
class ActionResult:
    message: str | None = None
    exit_code: int = 0
    is_error: bool = False
    stream_to_stderr: bool = False

    @staticmethod
    def ok() -> "ActionResult": return ActionResult()

    @staticmethod
    def error(message: str, exit_code: int = 1) -> "ActionResult":
        return ActionResult(message=message, exit_code=exit_code, is_error=True, stream_to_stderr=True)

    @staticmethod
    def info(message: str) -> "ActionResult": return ActionResult(message=message)


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
    if status in (HTTP_STATUS_UNAUTHORIZED, HTTP_STATUS_FORBIDDEN):
        return AUTH_REQUIRED
    if status == HTTP_STATUS_RATE_LIMITED or status >= HTTP_STATUS_SERVER_ERROR_FLOOR:
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
