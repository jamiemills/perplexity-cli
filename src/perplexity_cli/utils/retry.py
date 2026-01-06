"""Retry utilities with exponential backoff for network requests."""

import time
from collections.abc import Callable
from typing import TypeVar

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T")


def retry_with_backoff(
    max_attempts: int = 3,
    initial_wait: float = 1.0,
    max_wait: float = 10.0,
    exponential_base: float = 2.0,
) -> Callable[[Callable[[], T]], T]:
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
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
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
        httpx.RequestError: If all retry attempts fail.
        httpx.HTTPStatusError: If HTTP error persists after retries.
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
    if isinstance(exception, httpx.RequestError):
        return True

    # HTTP 5xx errors are retryable
    if isinstance(exception, httpx.HTTPStatusError):
        if exception.response.status_code >= 500:
            return True
        # Rate limiting (429) is retryable
        if exception.response.status_code == 429:
            return True

    return False


def sleep_with_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> None:
    """Sleep with exponential backoff.

    Args:
        attempt: Current attempt number (0-indexed).
        base_delay: Base delay in seconds.
        max_delay: Maximum delay in seconds.
    """
    delay = min(base_delay * (2**attempt), max_delay)
    time.sleep(delay)
