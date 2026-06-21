"""Retry utilities with exponential backoff for network requests."""

import time
from collections.abc import Callable
from secrets import SystemRandom
from typing import Final, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
)

_rng = SystemRandom()

_HTTP_STATUS_TOO_MANY_REQUESTS: Final[int] = 429
_HTTP_SERVER_ERROR_FLOOR: Final[int] = 500

T = TypeVar("T")


def retry_with_backoff(
    max_attempts: int = 3,
    initial_wait: float = 1.0,
    max_wait: float = 10.0,
    exponential_base: float = 2.0,
) -> Callable[[Callable[[], T]], Callable[[], T]]:
    """Create a retry decorator with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts.
        initial_wait: Initial wait time in seconds.
        max_wait: Maximum wait time in seconds.
        exponential_base: Base for exponential backoff calculation.

    Returns:
        Decorator function for retrying operations.
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=initial_wait, max=max_wait, exp_base=exponential_base),
        retry=retry_if_exception_type((PerplexityRequestError, PerplexityHTTPStatusError)),
        reraise=True,
    )


def retry_http_request[T](
    func: Callable[[], T],
    max_attempts: int = 3,
    initial_wait: float = 1.0,
    max_wait: float = 10.0,
) -> T:
    """Retry an HTTP request function with exponential backoff.

    Args:
        func: Function that performs HTTP request.
        max_attempts: Maximum number of retry attempts.
        initial_wait: Initial wait time in seconds.
        max_wait: Maximum wait time in seconds.

    Returns:
        Result of the function call.

    Raises:
        PerplexityRequestError: If all retry attempts fail.
        PerplexityHTTPStatusError: If HTTP error persists after retries.
    """
    retry_decorator = retry_with_backoff(
        max_attempts=max_attempts,
        initial_wait=initial_wait,
        max_wait=max_wait,
    )

    @retry_decorator
    def _retry_wrapper() -> T:
        return func()

    return _retry_wrapper()


def is_retryable_error(exception: Exception) -> bool:
    """Check if an exception is retryable.

    Args:
        exception: Exception to check.

    Returns:
        True if exception is retryable, False otherwise.
    """
    # Network errors are retryable
    if isinstance(exception, PerplexityRequestError):
        return True

    # HTTP 5xx errors are retryable
    if isinstance(exception, PerplexityHTTPStatusError):
        if exception.response.status_code >= _HTTP_SERVER_ERROR_FLOOR:
            return True
        # Rate limiting (429) is retryable
        if exception.response.status_code == _HTTP_STATUS_TOO_MANY_REQUESTS:
            return True

    return False


def sleep_with_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> None:
    """Sleep with exponential backoff.

    Args:
        attempt: Current attempt number (0-indexed).
        base_delay: Base delay in seconds.
        max_delay: Maximum delay in seconds.
    """
    delay = get_backoff_delay(attempt, base_delay=base_delay, max_delay=max_delay)
    time.sleep(delay)


def get_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter_factor: float = 0.1,
) -> float:
    """Calculate exponential backoff delay with bounded jitter."""
    delay = min(base_delay * (2**attempt), max_delay)
    if jitter_factor <= 0:
        return delay

    jitter_window = delay * jitter_factor
    jitter = _rng.uniform(-jitter_window, jitter_window)
    return max(0.0, min(delay + jitter, max_delay))


def get_retry_after_delay(exception: Exception) -> float | None:
    """Extract a Retry-After delay from an HTTP exception, if present."""
    if not isinstance(exception, PerplexityHTTPStatusError):
        return None

    retry_after = exception.response.headers.get("Retry-After") or exception.response.headers.get(
        "retry-after"
    )
    if retry_after is None:
        return None

    try:
        delay = float(retry_after)
    except ValueError:
        return None

    return max(0.0, delay)
