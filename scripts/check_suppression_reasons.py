"""Suppression-reason enforcement gate.

Blocks new inline suppressions (``# noqa``, ``# nosec``, ``# nosemgrep``)
that lack ``owner:`` and ``reason:`` justification fields.  Existing
un-annotated suppressions are grandfathered via a fingerprint baseline;
newly added suppressions must include both fields.

Format: ``# noqa: X; owner: name; reason: explanation``

Usage::

    uv run python scripts/check_suppression_reasons.py [--update-baseline]

Exit codes: 0 = pass, 1 = unformatted suppression found.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS: tuple[Path, ...] = (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "scripts",
)
BASELINE_DIR = PROJECT_ROOT / "quality" / "baselines"
BASELINE_NAME = "suppression-reasons.json"
_SCRIPT = Path(__file__).name

_SUPPRESSION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("noqa", re.compile(r"#\s*noqa\b(?:\s*:\s*(.+?))?(?=\s*$|\s*#)")),
    ("nosemgrep", re.compile(r"#\s*nosemgrep\b(?:\s*:\s*(.+?))?(?=\s*$|\s*#)")),
    ("nosec", re.compile(r"#\s*nosec\b")),
]

_OWNER_RE = re.compile(r"(?:^|[;\s,])owner\s*:\s*\S", re.IGNORECASE)
_REASON_RE = re.compile(r"(?:^|[;\s,])reason\s*:\s*\S", re.IGNORECASE)

DESCRIPTION = "Block new suppression comments without owner: and reason: fields."


def _make_fingerprint(relative_path: str, line_no: int, stype: str) -> str:
    """Create a stable fingerprint for a suppression on a given file and line.

    Args:
        relative_path: File path relative to the project root.
        line_no: One-based line number.
        stype: Suppression type (noqa, nosec, nosemgrep).

    Returns:
        A fingerprint string in ``file:line:type`` format.
    """
    return f"{relative_path}:{line_no}:{stype}"


def _any_owner_reason(line: str) -> bool:
    """Return True if the line contains both ``owner:`` and ``reason:`` fields."""
    return bool(_OWNER_RE.search(line)) and bool(_REASON_RE.search(line))


def _find_suppressions(relative_path: str, line_no: int, line: str) -> list[tuple[str, str, bool]]:
    """Extract suppressions from a single source line.

    Args:
        relative_path: File path relative to the project root.
        line_no: One-based line number.
        line: The source line text.

    Returns:
        List of (fingerprint, stype, is_formatted) tuples.
    """
    results: list[tuple[str, str, bool]] = []
    formatted = _any_owner_reason(line) if _SUPPRESSION_PATTERNS else False
    for stype, regex in _SUPPRESSION_PATTERNS:
        for _ in regex.finditer(line):
            fp = _make_fingerprint(relative_path, line_no, stype)
            results.append((fp, stype, formatted))
    return results


def _scan_source_files() -> list[tuple[str, str, bool]]:
    """Scan all Python source files for suppression comments.

    Returns:
        List of (fingerprint, stype, is_formatted) tuples.
    """
    results: list[tuple[str, str, bool]] = []
    for src_root in SOURCE_ROOTS:
        for py_file in sorted(src_root.rglob("*.py")):
            relative = str(py_file.relative_to(PROJECT_ROOT))
            try:
                text = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                logger.warning("Could not read %s", py_file)
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                results.extend(_find_suppressions(relative, line_no, line))
    return results


def _load_baseline() -> set[str]:
    """Load suppression fingerprints from the baseline file.

    Returns:
        A set of fingerprint strings, or an empty set when the baseline
        file is absent or unparseable.
    """
    path = BASELINE_DIR / BASELINE_NAME
    if not path.is_file():
        return set()
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not parse baseline %s", path)
        return set()
    fingerprints = baseline.get("fingerprints", [])
    return {str(fp) for fp in fingerprints}


def _save_baseline(fingerprints: list[str]) -> None:
    """Save suppression fingerprints to the baseline file.

    Args:
        fingerprints: List of fingerprint strings to persist.
    """
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    path = BASELINE_DIR / BASELINE_NAME
    unique = sorted(set(fingerprints))
    path.write_text(
        json.dumps({"fingerprints": unique}, indent=2) + "\n",
        encoding="utf-8",
    )


def _classify_suppressions(
    suppressions: list[tuple[str, str, bool]],
    baseline: set[str],
) -> tuple[list[tuple[str, str]], int, int]:
    """Classify suppressions as formatted, grandfathered, or unformatted.

    Args:
        suppressions: List of (fingerprint, stype, is_formatted) tuples.
        baseline: Set of grandfathered fingerprints.

    Returns:
        A tuple of (unformatted, formatted_count, grandfathered_count).
    """
    unformatted: list[tuple[str, str]] = []
    formatted_count = 0
    grandfathered_count = 0
    for fp, stype, formatted in suppressions:
        if formatted:
            formatted_count += 1
        elif fp in baseline:
            grandfathered_count += 1
        else:
            unformatted.append((fp, stype))
    return unformatted, formatted_count, grandfathered_count


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list, or None to use ``sys.argv``.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Record all current suppressions as the baseline.",
    )
    return parser.parse_args(argv)


def _report_unformatted(unformatted: list[tuple[str, str]]) -> int:
    """Report unformatted suppressions to stderr and return exit code 1.

    Args:
        unformatted: List of (fingerprint, stype) tuples for unformatted
            suppressions.

    Returns:
        Exit code 1.
    """
    print(
        "Suppression-reason enforcement FAILED: un-annotated suppression(s) found.\n",
        file=sys.stderr,
    )
    for fp, stype in sorted(unformatted):
        print(f"  {fp} ({stype}) — missing owner:/reason:", file=sys.stderr)
    print(
        "\nAll new suppression comments must include owner: and reason: fields:\n"
        "  # noqa: X; owner: name; reason: explanation\n"
        "\nAdd the fields, or grandfather existing suppressions:\n"
        f"  uv run python scripts/{_SCRIPT} --update-baseline",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> None:
    """Entry point.

    Args:
        argv: Argument list, or None to use ``sys.argv``.
    """
    args = _parse_args(argv)
    suppressions = _scan_source_files()

    if args.update_baseline:
        all_fps = [fp for fp, _st, _fmt in suppressions]
        _save_baseline(all_fps)
        print(f"Suppression-reason baseline saved: {len(all_fps)} fingerprint(s)")
        return

    baseline = _load_baseline()
    unformatted, formatted_count, grandfathered_count = _classify_suppressions(
        suppressions, baseline
    )

    if unformatted:
        sys.exit(_report_unformatted(unformatted))

    total = len(suppressions)
    print(
        f"Suppression-reason enforcement passed: {total} suppression(s) total; "
        f"{formatted_count} formatted, {grandfathered_count} grandfathered."
    )


if __name__ == "__main__":
    main()
