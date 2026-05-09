"""Centralised curl_cffi session factory.

Provides a single location controlling the TLS impersonation profile,
default timeouts, and the availability guard for ``curl_cffi``.  All
modules that need an HTTP session should create one through these
factory functions rather than importing ``curl_cffi`` directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

try:
    from curl_cffi.requests import AsyncSession, Session
    from curl_cffi.requests.exceptions import RequestException  # noqa: F401

    _CURL_CFFI_AVAILABLE = True
    _CURL_CFFI_IMPORT_ERROR: str | None = None
except ImportError as _exc:  # pragma: no cover
    AsyncSession = None  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]
    Session = None  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]
    RequestException = Exception  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]
    _CURL_CFFI_AVAILABLE = False
    _CURL_CFFI_IMPORT_ERROR = (
        f"curl_cffi is required but could not be imported: {_exc}. "
        "Install it with: uv pip install 'curl-cffi>=0.14.0'"
    )

if TYPE_CHECKING:
    from curl_cffi.requests import AsyncSession as AsyncSessionType
    from curl_cffi.requests import Session as SessionType

#: Default TLS impersonation profile used for all sessions.
IMPERSONATE_PROFILE = "chrome"


def is_curl_cffi_available() -> bool:
    """Return whether ``curl_cffi`` is importable on this platform."""
    return _CURL_CFFI_AVAILABLE


def _guard_curl_cffi() -> None:
    """Raise ``RuntimeError`` if ``curl_cffi`` is not available."""
    if not _CURL_CFFI_AVAILABLE:
        raise RuntimeError(_CURL_CFFI_IMPORT_ERROR)


def create_sync_session(timeout: int | None = None) -> SessionType:
    """Create a synchronous curl_cffi Session with Chrome TLS impersonation.

    Args:
        timeout: Request timeout in seconds (default from config/defaults).

    Returns:
        A ``Session`` configured for Chrome impersonation.

    Raises:
        RuntimeError: If curl_cffi is not installed.
    """
    if timeout is None:
        from perplexity_cli.config.defaults import DEFAULT_REQUEST_TIMEOUT

        timeout = DEFAULT_REQUEST_TIMEOUT

    _guard_curl_cffi()
    return Session(impersonate=IMPERSONATE_PROFILE, timeout=timeout)  # type: ignore[misc]


def create_async_session(timeout: int | None = None) -> AsyncSessionType:
    """Create an asynchronous curl_cffi AsyncSession with Chrome TLS impersonation.

    Args:
        timeout: Request timeout in seconds (default from config/defaults).

    Returns:
        An ``AsyncSession`` configured for Chrome impersonation.

    Raises:
        RuntimeError: If curl_cffi is not installed.
    """
    if timeout is None:
        from perplexity_cli.config.defaults import DEFAULT_REQUEST_TIMEOUT

        timeout = DEFAULT_REQUEST_TIMEOUT

    _guard_curl_cffi()
    return AsyncSession(impersonate=IMPERSONATE_PROFILE, timeout=timeout)  # type: ignore[misc]
