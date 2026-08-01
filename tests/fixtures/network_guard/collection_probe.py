"""Synthetic collection-time network probe.

This file is intentionally NOT collected by the main suite (it lives under
``tests/fixtures/``).  ``tests/test_network_guard.py`` executes it as a
subprocess with ``-p tests.support.network_guard`` to prove the guard is
installed before test-module collection, so even module-scope imports cannot
reach non-loopback hosts.
"""

import socket

_BLOCKED_AT_IMPORT = False
try:
    socket.create_connection(("93.184.216.34", 80), timeout=1.0)
except OSError as exc:
    _BLOCKED_AT_IMPORT = "Network guard" in str(exc)


def test_collection_time_connection_blocked() -> None:
    """Module-scope socket I/O must have been rejected by the guard."""
    assert _BLOCKED_AT_IMPORT
