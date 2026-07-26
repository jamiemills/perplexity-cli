"""Adversarial tests for the network guard fixture."""

from __future__ import annotations

import socket

import httpx
import pytest

from tests.support.network_guard import _patched_create_connection


def test_guard_blocks_external_v4() -> None:
    """The guard rejects an IPv4 non-loopback address."""
    with pytest.raises(OSError, match="blocked"):
        _patched_create_connection(("93.184.216.34", 80))


def test_guard_blocks_external_v6() -> None:
    """The guard also blocks external IPv6 addresses."""
    with pytest.raises(OSError, match="blocked"):
        _patched_create_connection(("2001:db8::1", 80, 0, 0))


def test_guard_blocks_external_hostname() -> None:
    """The guard blocks connections to external hostnames."""
    with pytest.raises(OSError, match="blocked"):
        _patched_create_connection(("example.com", 443))


def test_guard_allows_loopback_v4() -> None:
    """The guard passes through IPv4 loopback connections."""
    original = socket.create_connection
    try:
        socket.create_connection = _patched_create_connection
        socket.create_connection(("127.0.0.1", 0))
    except OSError as e:
        if "blocked" in str(e):
            pytest.fail(f"Guard incorrectly blocked loopback: {e}")
    finally:
        socket.create_connection = original


def _assert_not_blocked(address: tuple[str, int]) -> None:
    """Verify the guard does not block *address*.

    The connection will fail at the OS level (nothing listening on port
    0 or a non-existent loopback), but the guard itself must let the
    attempt pass through (i.e. raise a socket-level error, not an
    OSError containing ``blocked``).
    """
    try:
        _patched_create_connection(address)
    except OSError as e:
        if "blocked" in str(e):
            pytest.fail(f"Guard incorrectly blocked {address}: {e}")
    except ConnectionRefusedError:
        pass


def test_guard_allows_localhost() -> None:
    """The guard passes through 'localhost' connections."""
    _assert_not_blocked(("localhost", 0))


def test_guard_allows_loopback_v6() -> None:
    """The guard passes through IPv6 loopback."""
    _assert_not_blocked(("::1", 0))


def test_guard_allows_0_0_0_0() -> None:
    """The guard passes through 0.0.0.0 (bind-all, which is safe)."""
    _assert_not_blocked(("0.0.0.0", 0))


def test_guard_allows_127_x() -> None:
    """The guard allows any 127.x.x.x address."""
    _assert_not_blocked(("127.0.0.99", 0))


def test_guard_is_inactive_by_default(monkeypatch) -> None:
    """The autouse fixture does not activate without GUARD_NETWORK=1."""
    monkeypatch.delenv("GUARD_NETWORK", raising=False)
    assert socket.create_connection is not _patched_create_connection


def test_httpx_blocked_when_guard_active() -> None:
    """httpx connections to external hosts are blocked under the guard."""
    original = socket.create_connection
    try:
        socket.create_connection = _patched_create_connection
        with pytest.raises((OSError, httpx.ConnectError)):
            httpx.get("http://93.184.216.34/")
    finally:
        socket.create_connection = original


def test_guard_environment_variable_name_correct() -> None:
    """The guard uses the agreed environment variable name."""
    from tests.support.network_guard import _GUARD_ENV_VAR

    assert _GUARD_ENV_VAR == "GUARD_NETWORK", "Variable name must match documentation"
