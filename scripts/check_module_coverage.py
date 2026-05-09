"""Check that every module meets the per-module coverage threshold.

Reads the JSON report produced by ``pytest --cov --cov-report=json``
(default output: ``coverage.json``) and exits non-zero if any module
falls below the required minimum.

Usage::

    uv run python scripts/check_module_coverage.py [--min-coverage 85] [--report coverage.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_MIN_COVERAGE = 85
DEFAULT_REPORT = "coverage.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify per-module test coverage meets the minimum threshold.",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=DEFAULT_MIN_COVERAGE,
        help=f"Minimum coverage percentage per module (default: {DEFAULT_MIN_COVERAGE})",
    )
    parser.add_argument(
        "--report",
        type=str,
        default=DEFAULT_REPORT,
        help=f"Path to coverage JSON report (default: {DEFAULT_REPORT})",
    )
    return parser.parse_args()


def _load_report(path: str) -> dict:
    report_path = Path(path)
    if not report_path.is_file():
        print(f"Coverage report not found: {path}", file=sys.stderr)
        print("Run pytest with --cov --cov-report=json first.", file=sys.stderr)
        sys.exit(2)

    with report_path.open() as f:
        return json.load(f)


def _check_modules(data: dict, min_coverage: float) -> list[tuple[str, float, int, int]]:
    """Return a list of (module, percentage, statements, missing) for failing modules."""
    failures: list[tuple[str, float, int, int]] = []

    for filepath, entry in sorted(data.get("files", {}).items()):
        summary = entry.get("summary", {})
        pct = summary.get("percent_covered", 0.0)
        stmts = summary.get("num_statements", 0)
        miss = summary.get("missing_lines", 0)

        # Skip modules with very few statements (e.g. __init__.py with 0-2 lines)
        # as they can swing wildly on a single line change.
        if stmts < 5:
            continue

        if pct < min_coverage:
            module = filepath.replace("src/perplexity_cli/", "").replace(".py", "")
            failures.append((module, pct, stmts, miss))

    return failures


def main() -> None:
    args = _parse_args()
    data = _load_report(args.report)
    failures = _check_modules(data, args.min_coverage)

    if not failures:
        total_pct = data.get("totals", {}).get("percent_covered", 0.0)
        file_count = len(data.get("files", {}))
        print(
            f"Per-module coverage check passed: all {file_count} modules "
            f">= {args.min_coverage}% (overall: {total_pct:.1f}%)"
        )
        sys.exit(0)

    print(
        f"Per-module coverage check FAILED: {len(failures)} module(s) "
        f"below {args.min_coverage}%:\n",
        file=sys.stderr,
    )
    for module, pct, stmts, miss in failures:
        print(f"  {module}: {pct:.1f}% ({miss} of {stmts} statements missing)", file=sys.stderr)

    print(
        f"\nEvery module must have at least {args.min_coverage}% test coverage.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
