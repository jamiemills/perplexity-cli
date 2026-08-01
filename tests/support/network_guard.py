"""Fail-closed network isolation for non-live pytest lanes.

Installed automatically through ``tests/conftest.py`` plugin registration and
activated in ``pytest_configure``, i.e. before test-module collection, so even
module-level import I/O is rejected.  Every outbound connection must resolve
to loopback; anything else raises an ``OSError`` before real I/O occurs.

The guard covers Python socket entry points (``socket.create_connection``,
``socket.socket.connect``/``connect_ex``/``sendto``/``sendmsg`` and the DNS
helpers ``getaddrinfo``/``gethostbyname``/``gethostbyname_ex``/
``gethostbyaddr``/``getnameinfo``), which also contains ``httpx``,
``websockets`` and ``anyio``-based transports, plus every application
``curl_cffi`` entry point (the session factory functions, the exported
``Session``/``AsyncSession`` classes, and upload_manager's captured
``CurlAsyncSession``) so native libcurl traffic is rejected at the URL
boundary before delegation.

Only a node explicitly marked ``real_api`` with ``RUN_REAL_API_TESTS=1`` may
bypass the guard; that path remains unexecuted in this plan.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import pytest

_REAL_API_VAR = "RUN_REAL_API_TESTS"

_LOOPBACK_NAMES: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})

_PROXY_VARS: tuple[str, ...] = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)

_PERPLEXITY_ENDPOINT_VARS: tuple[str, ...] = (
    "PERPLEXITY_BASE_URL",
    "PERPLEXITY_QUERY_ENDPOINT",
    "PERPLEXITY_THREAD_LIST_ENDPOINT",
    "PERPLEXITY_UPLOAD_URL_ENDPOINT",
    "PERPLEXITY_S3_BUCKET_URL",
    "PERPLEXITY_MODEL_CONFIG_ENDPOINT",
    "PERPLEXITY_USER_SETTINGS_ENDPOINT",
)

_XDG_VARS: tuple[str, ...] = (
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
)

# HOME is intentionally not scrubbed: configuration isolation already
# redirects PERPLEXITY_CONFIG_DIR per test (conftest.isolate_config_dir) and
# scrubbing HOME would break Path.home()-based assertions.  No browser or
# credential environment variables are consumed anywhere in src/.
_SCRUBBED_VARS: tuple[str, ...] = _PROXY_VARS + _PERPLEXITY_ENDPOINT_VARS + _XDG_VARS


@dataclass
class _GuardState:
    """Mutable guard state; a module singleton avoids ``global`` mutation."""

    active: bool = False
    patched: bool = False
    saved_env: dict[str, str] = field(default_factory=dict)
    original_create_connection: Callable[..., Any] | None = None
    original_socket_class: type[socket.socket] = socket.socket
    original_dns: dict[str, Callable[..., Any]] = field(default_factory=dict)
    original_session_class: type[Any] | None = None
    original_async_session_class: type[Any] | None = None
    original_upload_class: type[Any] | None = None
    original_factories: tuple[Callable[..., Any], Callable[..., Any]] | None = None


_state = _GuardState()


# ---------------------------------------------------------------------------
# Loopback classification
# ---------------------------------------------------------------------------


def _host_from_address(address: Any) -> str:
    """Extract the host portion from a socket address."""
    if isinstance(address, str):
        return address
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


def is_loopback_host(host: str) -> bool:
    """Return True when *host* denotes a loopback destination.

    Accepts the literal ``localhost``, IPv4 loopback addresses
    (``127.0.0.0/8``), the IPv6 loopback ``::1`` and IPv4-mapped loopback
    forms (``::ffff:127.0.0.1``).  ``0.0.0.0`` is a bind wildcard, not a
    destination, and is therefore rejected.  Hostnames other than the literal
    ``localhost`` are rejected without DNS, so names such as
    ``127.0.0.1.evil.com`` cannot smuggle a connection past the guard.
    """
    normalized = host.strip().strip("[]").lower()
    if normalized in _LOOPBACK_NAMES:
        return True
    if normalized.startswith("::ffff:"):
        normalized = normalized[7:]
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _assert_loopback_host(host: str) -> None:
    """Raise ``OSError`` unless *host* is a loopback destination."""
    if not is_loopback_host(host):
        raise OSError(
            f"Network guard: external connection to {host!r} blocked "
            "(loopback-only test isolation is active)."
        )


def _assert_loopback_url(url: str) -> None:
    """Raise ``OSError`` unless *url* targets a loopback HTTP(S)/WS host."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https", "ws", "wss"):
        raise OSError(f"Network guard: unsupported URL scheme {parts.scheme!r} blocked.")
    _assert_loopback_host(parts.hostname or "")


# ---------------------------------------------------------------------------
# Socket interception
# ---------------------------------------------------------------------------


def _patched_create_connection(
    address: Any,
    timeout: float | None = socket._GLOBAL_DEFAULT_TIMEOUT,
    source_address: Any = None,
) -> socket.socket:
    """Reject non-loopback connections, otherwise delegate."""
    _assert_loopback_host(_host_from_address(address))
    assert _state.original_create_connection is not None
    return _state.original_create_connection(address, timeout, source_address)


class _GuardedSocket(socket.socket):
    """``socket.socket`` subclass rejecting non-loopback traffic."""

    def connect(self, address: Any) -> None:
        _assert_loopback_host(_host_from_address(address))
        return super().connect(address)

    def connect_ex(self, address: Any) -> int:
        _assert_loopback_host(_host_from_address(address))
        return super().connect_ex(address)

    def sendto(self, data: Any, address: Any = None, *args: Any) -> int:
        """Reject unconnected UDP/raw sends to non-loopback destinations."""
        _check_send_address(address, args)
        return super().sendto(data, address, *args)

    def sendmsg(self, buffers: Any, ancdata: Any = (), flags: int = 0, address: Any = None) -> int:
        """Reject unconnected sendmsg to non-loopback destinations."""
        if isinstance(address, (tuple, str)):
            _assert_loopback_host(_host_from_address(address))
        return super().sendmsg(buffers, ancdata, flags, address)


def _check_send_address(address: Any, args: tuple[Any, ...]) -> None:
    """Validate the destination in either ``sendto`` argument order."""
    if isinstance(address, (tuple, str)):
        _assert_loopback_host(_host_from_address(address))
    elif args and isinstance(args[0], (tuple, str)):
        _assert_loopback_host(_host_from_address(args[0]))


def _patched_getaddrinfo(
    host: Any,
    port: Any,
    family: int = 0,
    type: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> list[Any]:
    """Reject resolution of non-loopback hostnames without issuing DNS.

    ``host is None`` is a wildcard bind, not a destination, and is allowed.
    """
    if host is not None:
        _assert_loopback_host(_host_from_address(host))
    original = _state.original_dns["getaddrinfo"]
    return original(host, port, family, type, proto, flags)


def _patched_gethostbyname(host: str) -> str:
    """Reject resolution of non-loopback hostnames without issuing DNS."""
    _assert_loopback_host(_host_from_address(host))
    return _state.original_dns["gethostbyname"](host)


def _patched_gethostbyname_ex(host: str) -> tuple[str, list[str], list[str]]:
    """Reject resolution of non-loopback hostnames without issuing DNS."""
    _assert_loopback_host(_host_from_address(host))
    return _state.original_dns["gethostbyname_ex"](host)


def _patched_gethostbyaddr(ip_address: str) -> tuple[str, list[str], list[str]]:
    """Reject reverse lookups of non-loopback addresses."""
    _assert_loopback_host(_host_from_address(ip_address))
    return _state.original_dns["gethostbyaddr"](ip_address)


def _patched_getnameinfo(sockaddr: Any, flags: int) -> tuple[str, str]:
    """Reject name lookups for non-loopback addresses."""
    _assert_loopback_host(_host_from_address(sockaddr))
    return _state.original_dns["getnameinfo"](sockaddr, flags)


# ---------------------------------------------------------------------------
# Application curl_cffi interception (native libcurl bypasses Python sockets)
# ---------------------------------------------------------------------------


def _guarded_curl_method(original: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a curl session method with a URL check.

    Works for synchronous, asynchronous, generator and async-generator methods
    because the URL is validated at call time, before any native I/O starts.
    """

    def _wrap(*args: Any, **kwargs: Any) -> Any:
        url = args[1] if len(args) > 1 else kwargs.get("url")
        _assert_loopback_url(str(url))
        return original(*args, **kwargs)

    return _wrap


def _wrap_curl_session(session: Any) -> Any:
    """Install URL guards on a curl_cffi session instance."""
    if hasattr(session, "request"):
        session.request = _guarded_curl_method(session.request)
    if hasattr(session, "stream"):
        session.stream = _guarded_curl_method(session.stream)
    return session


def _wrap_curl_class(original_class: type[Any]) -> type[Any]:
    """Return a subclass whose instances carry the URL guards."""

    class _GuardedCurlClass(original_class):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            _wrap_curl_session(self)

    return _GuardedCurlClass


def _install_curl_factory_guard() -> None:
    """Route session creation through URL-guarded wrappers."""
    from perplexity_cli.utils import session_factory

    _state.original_factories = (
        session_factory.create_sync_session,
        session_factory.create_async_session,
    )

    def _guarded_sync(timeout: int | None = None) -> Any:
        assert _state.original_factories is not None
        return _wrap_curl_session(_state.original_factories[0](timeout=timeout))

    def _guarded_async(timeout: int | None = None) -> Any:
        assert _state.original_factories is not None
        return _wrap_curl_session(_state.original_factories[1](timeout=timeout))

    session_factory.create_sync_session = _guarded_sync
    session_factory.create_async_session = _guarded_async

    # Direct class entry points used by the thread scraper and upload manager.
    _state.original_session_class = session_factory.Session
    _state.original_async_session_class = session_factory.AsyncSession
    if _state.original_session_class is not None:
        session_factory.Session = _wrap_curl_class(_state.original_session_class)
    if _state.original_async_session_class is not None:
        session_factory.AsyncSession = _wrap_curl_class(_state.original_async_session_class)

    from perplexity_cli.attachments import upload_manager

    _state.original_upload_class = upload_manager.CurlAsyncSession
    if _state.original_upload_class is not None:
        upload_manager.CurlAsyncSession = _wrap_curl_class(_state.original_upload_class)


def _restore_curl_factory_guard() -> None:
    """Restore the original session classes and factory functions."""
    if _state.original_factories is None:
        return
    from perplexity_cli.utils import session_factory

    session_factory.create_sync_session, session_factory.create_async_session = (
        _state.original_factories
    )
    _state.original_factories = None

    if _state.original_session_class is not None:
        session_factory.Session = _state.original_session_class
        _state.original_session_class = None
    if _state.original_async_session_class is not None:
        session_factory.AsyncSession = _state.original_async_session_class
        _state.original_async_session_class = None
    if _state.original_upload_class is not None:
        from perplexity_cli.attachments import upload_manager

        upload_manager.CurlAsyncSession = _state.original_upload_class
        _state.original_upload_class = None


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------


def install_guard() -> None:
    """Install the fail-closed guard and scrub inherited environment."""
    if _state.patched:
        return
    _state.patched = True
    _state.active = True

    _state.saved_env = {}
    for var in _SCRUBBED_VARS:
        if var in os.environ:
            _state.saved_env[var] = os.environ.pop(var)

    _state.original_create_connection = socket.create_connection
    _state.original_socket_class = socket.socket
    _state.original_dns = {
        "getaddrinfo": socket.getaddrinfo,
        "gethostbyname": socket.gethostbyname,
        "gethostbyname_ex": socket.gethostbyname_ex,
        "gethostbyaddr": socket.gethostbyaddr,
        "getnameinfo": socket.getnameinfo,
    }

    socket.create_connection = _patched_create_connection
    socket.socket = _GuardedSocket
    socket.getaddrinfo = _patched_getaddrinfo
    socket.gethostbyname = _patched_gethostbyname
    socket.gethostbyname_ex = _patched_gethostbyname_ex
    socket.gethostbyaddr = _patched_gethostbyaddr
    socket.getnameinfo = _patched_getnameinfo
    _install_curl_factory_guard()


def uninstall_guard() -> None:
    """Restore the original socket/factory state and environment."""
    if not _state.patched:
        return
    _state.patched = False
    _state.active = False

    if _state.original_create_connection is not None:
        socket.create_connection = _state.original_create_connection
        _state.original_create_connection = None
    socket.socket = _state.original_socket_class
    for name, original in _state.original_dns.items():
        setattr(socket, name, original)
    _state.original_dns.clear()
    _restore_curl_factory_guard()

    for var, value in _state.saved_env.items():
        os.environ[var] = value
    _state.saved_env.clear()


def assert_guard_active() -> None:
    """Fail closed if the guard is not currently installed."""
    if not _state.active:
        raise AssertionError("Network guard is not active; external I/O is not isolated.")


def is_guard_active() -> bool:
    """Return whether the fail-closed guard is currently installed."""
    return _state.active


# ---------------------------------------------------------------------------
# Pytest plugin hooks
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Install the guard before test-module collection."""
    install_guard()


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore sockets and environment at session end."""
    uninstall_guard()


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Keep the guard active, with the narrow unexecuted live-API bypass."""
    if item.get_closest_marker("real_api") and os.environ.get(_REAL_API_VAR) == "1":
        uninstall_guard()
    else:
        install_guard()


def pytest_runtest_teardown(item: pytest.Item, nextitem: Any) -> None:
    """Reinstall the guard after every test."""
    install_guard()
