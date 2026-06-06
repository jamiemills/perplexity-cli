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

import pytest

from scripts import agent_check, generate_sonar_reports

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_no_scan_failing_vulnerabilities() -> None:
    """Safety scan finds no unresolved (scan-failing) vulnerabilities."""
    result = subprocess.run(
        ["make", "safety"],
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
        "  3. Run 'make safety' for details."
    )


def test_safety_stage_uses_only_intentional_inputs() -> None:
    inputs = agent_check.SAFETY_INPUT_PATHS

    assert inputs == (
        "pyproject.toml",
        "uv.lock",
        "src",
        "tests",
        "scripts",
        "vulture_whitelist.py",
    )
    assert ".venv" not in inputs
    assert ".opencode" not in inputs
    assert "mutants" not in inputs
    assert "build" not in inputs
    assert "dist" not in inputs
    assert "coverage.xml" not in inputs
    assert "coverage.json" not in inputs


def test_sonar_reports_target_only_source_inputs() -> None:
    assert generate_sonar_reports.SOURCE_DIR == PROJECT_ROOT / "src"
    assert generate_sonar_reports.REPORT_DIR == PROJECT_ROOT / "build" / "reports"

    bandit_command = generate_sonar_reports.TOOLS[0].command
    assert str(PROJECT_ROOT / "src") in bandit_command
    assert str(generate_sonar_reports.REPORT_DIR / "bandit-report.json") in bandit_command
    assert ".venv" not in bandit_command
    assert "build/reports" not in bandit_command


@pytest.mark.integration
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
