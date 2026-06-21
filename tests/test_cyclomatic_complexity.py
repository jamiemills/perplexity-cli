"""Radon code quality enforcement tests.

These tests run radon programmatically to ensure:
1. No function or method exceeds A-grade cyclomatic complexity (CC <= 5).
2. No module falls below A-grade maintainability index (MI >= 20).

Both metrics are enforced as regression guards after the codebase-wide
refactoring that brought all blocks and modules to A-grade.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

# Minimum grade that triggers a failure.  "-n B" tells radon to report
# only items scoring B or worse.  An empty report means everything is
# A-grade.
FAIL_ABOVE = "B"


def test_cyclomatic_complexity_all_a_grade() -> None:
    """Every function and method in src/ has cyclomatic complexity <= 5 (A-grade)."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "radon",
            "cc",
            str(SRC_DIR),
            "-s",
            "-n",
            FAIL_ABOVE,
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    output = result.stdout.strip()
    assert output == "", (
        f"Radon found blocks with cyclomatic complexity >= {FAIL_ABOVE}:\n"
        f"{output}\n\n"
        "Refactor these blocks to reduce complexity to A-grade (CC <= 5).  "
        "Common techniques: extract helper functions, use dispatch tables, "
        "apply early returns, or introduce guard clauses."
    )


def test_maintainability_index_all_a_grade() -> None:
    """Every module in src/ has maintainability index >= 20 (A-grade)."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "radon",
            "mi",
            str(SRC_DIR),
            "-s",
            "-n",
            FAIL_ABOVE,
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    output = result.stdout.strip()
    assert output == "", (
        f"Radon found modules with maintainability index >= {FAIL_ABOVE}:\n"
        f"{output}\n\n"
        "Improve these modules to reach A-grade (MI >= 20).  "
        "Common techniques: reduce complexity, add documentation, "
        "shorten functions, and reduce line count per module."
    )


def test_radon_is_importable() -> None:
    """Radon is installed and importable."""
    import radon  # noqa: F401
