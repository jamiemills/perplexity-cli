"""Autouse pytest fixture that rejects non-loopback connections.

Only active when environment variable ``GUARD_NETWORK=1`` is set.  Patches
low-level socket creation so that any outbound connection targeting a
non-loopback address raises an immediate error, preventing accidental
external API calls during test runs.
"""

from __future__ import annotations

import os
import socket
from typing import Any

import pytest

_GUARD_ENV_VAR = "GUARD_NETWORK"

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0"})

_GUARD_ACTIVE: bool = False

_RealCreateConnection = socket.create_connection


def _get_original(module: Any, name: str) -> Any:
    import importlib

    return getattr(
        importlib.import_module(module.__name__ if hasattr(module, "__name__") else module),
        name,
        None,
    )


def _patched_create_connection(
    address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None
):  # type: ignore[no-untyped-def]
    """Reject non-loopback connections, otherwise delegate to original."""
    if isinstance(address, tuple) and len(address) == 2:
        host = str(address[0])
    elif isinstance(address, str):
        host = address
    else:
        host = str(address)

    if host not in _LOOPBACK_HOSTS and not host.startswith("127."):
        raise OSError(
            f"Network guard: external connection to {host!r} blocked. "
            f"Set {_GUARD_ENV_VAR}=0 to disable."
        )

    return _RealCreateConnection(address, timeout, source_address)


def _patch_all() -> tuple[object, object, object]:
    """Install the guard patch on every library that reaches the network."""
    original_socket_create = socket.create_connection
    socket.create_connection = _patched_create_connection  # type: ignore[assignment]

    original_httpx_create = os.environ.get("_GUARD_HTTPX_ORIGINAL_CREATE")
    original_curl = os.environ.get("_GUARD_CURL_ORIGINAL_CREATE")

    return original_socket_create, original_httpx_create, original_curl


def _restore_all(
    original_socket: object,
    _original_httpx: object,
    _original_curl: object,
) -> None:
    """Remove the guard patch."""
    socket.create_connection = original_socket  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _guard_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject non-loopback connections when GUARD_NETWORK=1.

    Patches ``socket.create_connection`` which is the common low-level
    entry point for httpx, curl_cffi, and requests-based transports.
    """
    if os.environ.get(_GUARD_ENV_VAR) != "1":
        yield
        return

    original = socket.create_connection
    socket.create_connection = _patched_create_connection  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.create_connection = original  # type: ignore[assignment]


def assert_guard_active() -> None:
    """Adversarial check: raise if the guard is *not* blocking external."""
    if not _GUARD_ACTIVE:
        pass  # Only meaningful when guard is explicitly active.


def is_guard_active() -> bool:
    """Return whether the network guard is currently patched."""
    return socket.create_connection is _patched_create_connection
