"""Centralised curl_cffi session factory.

Provides a single location controlling the TLS impersonation profile,
default timeouts, and the availability guard for ``curl_cffi``.  All
modules that need an HTTP session should create one through these
factory functions rather than importing ``curl_cffi`` directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

Session: type | None = None
AsyncSession: type | None = None
_curl_cffi_available = False
_curl_cffi_import_error: str | None = None

try:
    from curl_cffi.requests import AsyncSession as _AsyncSessionCls
    from curl_cffi.requests import Session as _SessionCls

    Session = _SessionCls
    AsyncSession = _AsyncSessionCls
    _curl_cffi_available = True
    _curl_cffi_import_error = None  # pragma: no cover
except ImportError as _exc:  # pragma: no cover
    _curl_cffi_import_error = (
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
    return _curl_cffi_available


def _guard_curl_cffi() -> None:
    """Raise ``RuntimeError`` if ``curl_cffi`` is not available."""
    if not _curl_cffi_available:
        raise RuntimeError(_curl_cffi_import_error)


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
    session_cls = Session
    if session_cls is None:  # pragma: no cover
        raise RuntimeError(_curl_cffi_import_error)
    return session_cls(impersonate=IMPERSONATE_PROFILE, timeout=timeout)


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
    async_session_cls = AsyncSession
    if async_session_cls is None:  # pragma: no cover
        raise RuntimeError(_curl_cffi_import_error)
    return async_session_cls(impersonate=IMPERSONATE_PROFILE, timeout=timeout)
