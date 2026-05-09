"""Dead code detection tests using vulture.

These tests run vulture programmatically to ensure no dead code is
introduced into the source tree.  The whitelist file
(vulture_whitelist.py) suppresses known false positives such as
Pydantic validators, model fields, context-manager protocol parameters,
and functions exercised only through the test suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
WHITELIST = PROJECT_ROOT / "vulture_whitelist.py"

# Minimum confidence threshold -- 80% filters out most speculative
# reports while still catching clearly unused code.
MIN_CONFIDENCE = 80


def test_no_dead_code_in_source() -> None:
    """Vulture finds no dead code in src/ at the configured confidence level."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "vulture",
            str(SRC_DIR),
            str(WHITELIST),
            f"--min-confidence={MIN_CONFIDENCE}",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    assert result.returncode == 0, (
        f"Vulture detected dead code (confidence >= {MIN_CONFIDENCE}%):\n"
        f"{result.stdout}\n"
        "If these are false positives, add them to vulture_whitelist.py "
        "with a comment explaining why they are expected."
    )


def test_whitelist_file_exists() -> None:
    """The vulture whitelist file exists at the project root."""
    assert WHITELIST.is_file(), (
        f"Vulture whitelist not found at {WHITELIST}. "
        "This file is required to suppress known false positives."
    )


def test_vulture_is_importable() -> None:
    """Vulture is installed and importable."""
    import vulture  # noqa: F401
