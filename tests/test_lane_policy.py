"""Structural lane-policy tests for the pytest marker taxonomy.

Enforces the lane policy owned by T021:
1. Ordinary-lane test files carry no module-level ``real_api``/``manual``
   marker (those markers are reserved for genuinely live or interactive
   files).
2. Hermetic protocol integration files are marked ``hermetic_integration``.
3. Hermetic-marked files contain no live-API classes.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

HERMETIC_FILES = frozenset(
    {
        "test_query_protocol_integration.py",
        "test_attachment_protocol_integration.py",
        "test_api_protocol_integration.py",
    }
)

# Files that are genuinely live or interactive and may legitimately carry
# module-level real_api/manual markers without joining the ordinary lane.
LIVE_OR_INTERACTIVE_FILES = frozenset(
    {
        "test_api_integration.py",
        "test_file_attachment_real_e2e.py",
        "test_manual_auth.py",
        "test_query_simple.py",
        "test_query_realtime.py",
        "test_chrome_connection.py",
    }
)

LIVE_CLASS_NAMES = ("TestPerplexityAPIIntegration", "TestAPIErrorHandling")

_MODULE_PYTESTMARK_RE = re.compile(r"pytestmark\s*=\s*\[(.*?)\]", re.DOTALL)


def _module_pytestmark(source: str) -> str:
    """Return the contents of a module-level ``pytestmark = [...]``."""
    match = _MODULE_PYTESTMARK_RE.search(source)
    return match.group(1) if match else ""


def _ordinary_lane_files() -> list[Path]:
    return sorted(
        path for path in TESTS_DIR.glob("test_*.py") if path.name not in LIVE_OR_INTERACTIVE_FILES
    )


def test_ordinary_lane_files_have_no_module_level_live_or_manual_markers() -> None:
    """Ordinary-lane modules must not carry module-level real_api/manual markers."""
    for path in _ordinary_lane_files():
        marker_text = _module_pytestmark(path.read_text(encoding="utf-8"))
        assert "real_api" not in marker_text, (
            f"{path.name} carries a module-level real_api marker but is an ordinary-lane file"
        )
        assert "manual" not in marker_text, (
            f"{path.name} carries a module-level manual marker but is an ordinary-lane file"
        )


def test_hermetic_files_are_marked_hermetic_integration() -> None:
    """Hermetic protocol integration files carry the hermetic marker."""
    for name in sorted(HERMETIC_FILES):
        path = TESTS_DIR / name
        assert path.exists(), f"hermetic file {name} is missing"
        marker_text = _module_pytestmark(path.read_text(encoding="utf-8"))
        assert "hermetic_integration" in marker_text, (
            f"{name} must carry a module-level hermetic_integration marker"
        )


def test_hermetic_files_contain_no_live_classes() -> None:
    """Hermetic-marked files must not contain live-API classes."""
    for name in sorted(HERMETIC_FILES):
        source = (TESTS_DIR / name).read_text(encoding="utf-8")
        assert "RUN_REAL_API_TESTS" not in source, f"{name} references the live API runner"
        assert "pytest.mark.real_api" not in source, f"{name} carries a real_api marker"
        for class_name in LIVE_CLASS_NAMES:
            assert class_name not in source, f"{name} contains the live class {class_name}"
