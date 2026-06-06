"""Semgrep clean-code rule enforcement tests.

These tests run semgrep with the project's custom rules (.semgrep.yml)
and community rulesets (p/python, p/comment, p/r2c-best-practices) to
ensure no WARNING or ERROR-severity findings are present in the source
tree.  INFO-level findings are advisory and do not block.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEMGREP_CONFIG = PROJECT_ROOT / ".semgrep.yml"

_SEMGREP_BIN = shutil.which("semgrep")


def _run_semgrep(*extra_args: str) -> subprocess.CompletedProcess[str]:
    """Run semgrep against the project root and return the result."""
    assert _SEMGREP_BIN is not None, "semgrep binary not found on PATH"
    cmd = [
        _SEMGREP_BIN,
        "--config",
        str(SEMGREP_CONFIG),
        "--config",
        "p/python",
        "--config",
        "p/comment",
        "--config",
        "p/r2c-best-practices",
        "--severity",
        "ERROR",
        "--severity",
        "WARNING",
        "--exclude-rule",
        "python.lang.maintainability.useless-innerfunction.useless-inner-function",
        "--exclude",
        "tests/",
        "--error",
        "--metrics=off",
        *extra_args,
        ".",
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=120,
    )


@pytest.mark.skipif(_SEMGREP_BIN is None, reason="semgrep not installed")
def test_semgrep_config_exists() -> None:
    """The project semgrep configuration file exists."""
    assert SEMGREP_CONFIG.is_file(), (
        f"Semgrep config not found at {SEMGREP_CONFIG}. "
        "This file defines the project's custom clean-code rules."
    )


@pytest.mark.skipif(_SEMGREP_BIN is None, reason="semgrep not installed")
def test_no_semgrep_warnings_or_errors() -> None:
    """Semgrep finds zero WARNING/ERROR-severity findings in the source tree."""
    result = _run_semgrep()

    assert result.returncode == 0, (
        "Semgrep detected WARNING or ERROR-level findings:\n"
        f"{result.stdout}\n{result.stderr}\n"
        "Fix the findings, or add an inline '# nosemgrep: <rule-id>' "
        "comment with a justification if the finding is a false positive."
    )
