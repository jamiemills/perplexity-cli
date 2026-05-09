"""Supply-chain vulnerability scanning tests using Safety CLI.

These tests run Safety programmatically to ensure no unresolved
vulnerabilities exist in the project's dependency tree.  Vulnerabilities
that are covered by the Safety Platform policy (i.e. policy-ignored) do
not cause a failure -- only scan-failing findings trigger a non-zero
exit code from Safety.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_no_scan_failing_vulnerabilities() -> None:
    """Safety scan finds no unresolved (scan-failing) vulnerabilities."""
    result = subprocess.run(
        ["uvx", "safety", "scan", "--target", str(PROJECT_ROOT)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    assert result.returncode == 0, (
        "Safety scan found vulnerabilities that are not covered by policy:\n"
        f"{result.stdout}\n{result.stderr}\n\n"
        "To resolve:\n"
        "  1. Bump the affected dependency to a fixed version.\n"
        "  2. Or add a policy ignore rule on the Safety Platform.\n"
        "  3. Run 'uvx safety scan --target . --detailed-output' for details."
    )


def test_safety_cli_available() -> None:
    """Safety CLI is available via uvx."""
    result = subprocess.run(
        ["uvx", "safety", "--version"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "Safety CLI is not available. Ensure it can be run via 'uvx safety'.\n"
        f"stderr: {result.stderr}"
    )
