"""Tests for unconditional per-module coverage enforcement."""

from __future__ import annotations

import pytest

from scripts.check_module_coverage import _check_modules


def test_small_module_below_threshold_fails() -> None:
    """Modules below five statements remain subject to the configured floor."""
    report = {
        "files": {
            "src/perplexity_cli/tiny.py": {
                "summary": {
                    "percent_covered": 0.0,
                    "num_statements": 4,
                    "missing_lines": 4,
                }
            }
        }
    }

    assert _check_modules(report, 85.0) == [("tiny", 0.0, 4, 4)]


def test_empty_report_fails_closed() -> None:
    """Missing module data cannot be interpreted as full coverage."""
    with pytest.raises(ValueError, match="no module entries"):
        _check_modules({"files": {}}, 85.0)
