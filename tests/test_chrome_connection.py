#!/usr/bin/env python3
"""Manual Chrome DevTools connectivity test.

Marked ``manual`` so ordinary test lanes never contact port 9222.  When
run with ``pytest -m manual -s`` it FAILS with a clear assertion if Chrome
is unreachable or returns a malformed payload; it never silently passes by
returning ``False``.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

import pytest
import websockets

_CHROME_DEBUG_URL = "http://localhost:9222/json"
_CHROME_HINT = (
    "Ensure Chrome is running with --remote-debugging-port=9222 (run with pytest -m manual -s)"
)


async def _connect_and_verify() -> bool:
    """Connect to Chrome DevTools and verify a command round-trip.

    Returns:
        True when Chrome responds correctly; False otherwise with a
        diagnostic already printed to stdout.
    """
    targets = _fetch_targets()
    page_target = _find_page_target(targets)
    ws_url = page_target.get("webSocketDebuggerUrl")
    if not ws_url:
        print("✗ No WebSocket URL available for the page target")
        return False

    print(f"✓ Found page target: {ws_url}")
    async with websockets.connect(ws_url) as ws:
        command = {"id": 1, "method": "Browser.getVersion"}
        await ws.send(json.dumps(command))
        response = await ws.recv()
        data = json.loads(response)
        if "result" not in data:
            print(f"✗ Chrome returned no Browser.getVersion result: {data}")
            return False
        print(f"✓ Chrome Version: {data['result'].get('product', 'unknown')}")
    return True


def _fetch_targets() -> list[dict[str, object]]:
    """Fetch Chrome debugging targets or fail with a clear message."""
    try:
        with urllib.request.urlopen(_CHROME_DEBUG_URL, timeout=5) as response:
            payload = json.loads(response.read())
    except urllib.error.URLError as exc:
        pytest.fail(f"Chrome DevTools unreachable at {_CHROME_DEBUG_URL}: {exc}. {_CHROME_HINT}")
    except Exception as exc:
        pytest.fail(f"Chrome DevTools returned malformed data: {exc}")

    if not isinstance(payload, list):
        pytest.fail(f"Chrome returned an invalid targets payload: {payload!r}")
    return payload


def _find_page_target(targets: list[dict[str, object]]) -> dict[str, object]:
    """Return the first page target or fail with a clear message."""
    for target in targets:
        if isinstance(target, dict) and target.get("type") == "page":
            return target
    pytest.fail(f"No page target found in Chrome DevTools targets. {_CHROME_HINT}")


@pytest.mark.manual
@pytest.mark.asyncio
async def test_chrome_connection() -> None:
    """Manual test: verify a Chrome DevTools WebSocket round-trip."""
    ok = await _connect_and_verify()
    assert ok, f"Chrome DevTools connection FAILED (see diagnostics above). {_CHROME_HINT}"


if __name__ == "__main__":
    try:
        result = asyncio.run(_connect_and_verify())
    except BaseException as exc:
        print(f"Chrome connection check FAILED: {exc}")
        raise SystemExit(1) from exc
    raise SystemExit(0 if result else 1)
