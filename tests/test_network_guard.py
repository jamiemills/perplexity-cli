"""Adversarial tests for the fail-closed network guard.

The guard is installed automatically at session start (``pytest_configure``),
so every test in this module runs with isolation active by default.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import websockets

from tests.support import network_guard

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROBE = Path(__file__).resolve().parents[0] / "fixtures" / "network_guard" / "collection_probe.py"


def _guard_message_present(exc: BaseException) -> bool:
    """Return True when any exception in the chain mentions the guard."""
    current: BaseException | None = exc
    for _ in range(10):
        if current is None:
            return False
        if "Network guard" in str(current):
            return True
        current = current.__cause__
    return False


# ---------------------------------------------------------------------------
# Guard installation
# ---------------------------------------------------------------------------


def test_guard_is_active_by_default() -> None:
    """The guard must be active for ordinary tests without any opt-in."""
    assert network_guard.is_guard_active()


def test_assert_guard_active_fails_closed_when_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    """assert_guard_active must fail when the guard is not installed."""
    monkeypatch.setattr(network_guard._state, "active", False)
    with pytest.raises(AssertionError, match="not active"):
        network_guard.assert_guard_active()


# ---------------------------------------------------------------------------
# Socket interception
# ---------------------------------------------------------------------------


def test_guard_blocks_create_connection_external() -> None:
    """socket.create_connection to a public IPv4 address is rejected."""
    with pytest.raises(OSError, match="Network guard"):
        socket.create_connection(("93.184.216.34", 80))


def test_guard_blocks_socket_connect() -> None:
    """socket.socket.connect to a public address is rejected."""
    with pytest.raises(OSError, match="Network guard"):
        socket.socket().connect(("93.184.216.34", 80))


def test_guard_blocks_socket_connect_ex() -> None:
    """socket.socket.connect_ex to a public address is rejected."""
    with pytest.raises(OSError, match="Network guard"):
        socket.socket().connect_ex(("93.184.216.34", 80))


def test_guard_blocks_external_hostname_resolution() -> None:
    """getaddrinfo for a public hostname is rejected without issuing DNS."""
    with pytest.raises(OSError, match="Network guard"):
        socket.getaddrinfo("example.com", 443)


def test_guard_rejects_zero_address_as_destination() -> None:
    """0.0.0.0 is a bind wildcard and must not be treated as loopback."""
    with pytest.raises(OSError, match="Network guard"):
        socket.create_connection(("0.0.0.0", 80))


def test_guard_rejects_hostname_with_loopback_prefix() -> None:
    """A hostname like 127.0.0.1.evil.com must not pass the prefix check."""
    with pytest.raises(OSError, match="Network guard"):
        socket.create_connection(("127.0.0.1.evil.com", 80))
    with pytest.raises(OSError, match="Network guard"):
        socket.socket().connect(("127.0.0.1.evil.com", 80))


def test_guard_blocks_udp_sendto_external() -> None:
    """Unconnected UDP sends to public addresses are rejected."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(OSError, match="Network guard"):
            sock.sendto(b"probe", ("93.184.216.34", 53))
    finally:
        sock.close()


def test_guard_blocks_sendmsg_external() -> None:
    """Unconnected sendmsg to public addresses is rejected."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(OSError, match="Network guard"):
            sock.sendmsg([b"probe"], address=("93.184.216.34", 53))
    finally:
        sock.close()


def test_guard_blocks_legacy_dns_helpers() -> None:
    """Legacy DNS helpers are guarded without issuing external queries."""
    with pytest.raises(OSError, match="Network guard"):
        socket.gethostbyname("example.com")
    with pytest.raises(OSError, match="Network guard"):
        socket.gethostbyname_ex("example.com")
    with pytest.raises(OSError, match="Network guard"):
        socket.gethostbyaddr("93.184.216.34")


def test_guard_allows_wildcard_bind_resolution() -> None:
    """getaddrinfo(None, ...) is a wildcard bind, not a destination."""
    result = socket.getaddrinfo(None, 0)
    assert result


def test_guard_allows_loopback_delegation() -> None:
    """Loopback connections delegate to the real stack (closed port 0)."""
    try:
        socket.create_connection(("127.0.0.1", 0))
    except OSError as exc:
        assert "Network guard" not in str(exc)
    else:
        pytest.fail("expected a connection failure on closed loopback port 0")


def test_guard_allows_localhost_name_delegation() -> None:
    """The literal hostname localhost is allowed."""
    try:
        socket.create_connection(("localhost", 0))
    except OSError as exc:
        assert "Network guard" not in str(exc)
    else:
        pytest.fail("expected a connection failure on closed loopback port 0")


def test_guard_allows_loopback_v6_delegation() -> None:
    """IPv6 loopback is allowed."""
    try:
        socket.create_connection(("::1", 0))
    except OSError as exc:
        assert "Network guard" not in str(exc)
    else:
        pytest.fail("expected a connection failure on closed loopback port 0")


# ---------------------------------------------------------------------------
# Higher-level transports
# ---------------------------------------------------------------------------


def test_httpx_external_request_blocked() -> None:
    """httpx requests to public hosts fail with guard attribution."""
    with pytest.raises(httpx.ConnectError) as excinfo:
        httpx.get("http://93.184.216.34/")
    assert _guard_message_present(excinfo.value)


@pytest.mark.asyncio
async def test_websocket_external_connect_blocked() -> None:
    """websockets.connect to a public host fails with guard attribution."""
    try:
        async with websockets.connect("ws://93.184.216.34/"):
            pass
    except Exception as exc:  # transport wrappers vary by version
        assert _guard_message_present(exc)
    else:
        pytest.fail("external WebSocket connection was not blocked")


def test_curl_sync_session_factory_blocks_external_url() -> None:
    """Native curl_cffi sync sessions are guarded at the URL boundary."""
    from perplexity_cli.utils.session_factory import create_sync_session

    session = create_sync_session()
    try:
        with pytest.raises(OSError, match="Network guard"):
            session.get("http://93.184.216.34/")
    finally:
        session.close()


def test_curl_sync_session_factory_blocks_external_stream() -> None:
    """Native curl_cffi sync streams are guarded at the URL boundary."""
    from perplexity_cli.utils.session_factory import create_sync_session

    session = create_sync_session()
    try:
        with pytest.raises(OSError, match="Network guard"):
            session.stream("GET", "http://93.184.216.34/")
    finally:
        session.close()


@pytest.mark.asyncio
async def test_curl_async_session_factory_blocks_external_url() -> None:
    """Native curl_cffi async sessions are guarded at the URL boundary."""
    from perplexity_cli.utils.session_factory import create_async_session

    session = create_async_session()
    try:
        with pytest.raises(OSError, match="Network guard"):
            await session.get("http://93.184.216.34/")
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_curl_async_class_entry_point_blocked() -> None:
    """Direct session_factory.AsyncSession use (scraper path) is guarded."""
    from perplexity_cli.utils.session_factory import AsyncSession

    session = AsyncSession(impersonate="chrome", timeout=30)
    try:
        with pytest.raises(OSError, match="Network guard"):
            await session.get("http://93.184.216.34/")
        with pytest.raises(OSError, match="Network guard"):
            session.stream("GET", "http://93.184.216.34/")
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_curl_upload_manager_class_entry_point_blocked() -> None:
    """upload_manager's captured CurlAsyncSession is guarded."""
    from perplexity_cli.attachments.upload_manager import CurlAsyncSession

    if CurlAsyncSession is None:
        pytest.skip("curl_cffi unavailable on this platform")
    session = CurlAsyncSession(impersonate="chrome", timeout=30)
    try:
        with pytest.raises(OSError, match="Network guard"):
            await session.get("http://93.184.216.34/")
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Collection-time protection
# ---------------------------------------------------------------------------


def test_guard_active_during_module_collection_subprocess() -> None:
    """A module whose import performs non-loopback I/O must be blocked."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(_PROBE),
            "-p",
            "tests.support.network_guard",
            "-q",
            "--no-header",
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


# ---------------------------------------------------------------------------
# Environment scrubbing
# ---------------------------------------------------------------------------


def test_inherited_proxy_variables_scrubbed() -> None:
    """Proxy variables inherited from the developer/CI environment are removed."""
    for var in network_guard._PROXY_VARS:
        assert var not in os.environ


def test_inherited_perplexity_endpoint_variables_scrubbed() -> None:
    """Perplexity endpoint overrides inherited from the environment are removed."""
    for var in network_guard._PERPLEXITY_ENDPOINT_VARS:
        assert var not in os.environ
