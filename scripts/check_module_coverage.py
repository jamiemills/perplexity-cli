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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gates import load_gates

_gates = load_gates()
DEFAULT_MIN_COVERAGE = _gates.get_int("MIN_COVERAGE", 85)
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


def _check_modules(coverage_data: dict, min_coverage: float) -> list[tuple[str, float, int, int]]:
    """Return a list of (module, percentage, statements, missing) for failing modules."""
    failures: list[tuple[str, float, int, int]] = []
    files = coverage_data.get("files")
    if not isinstance(files, dict) or not files:
        msg = "Coverage report contains no module entries."
        raise ValueError(msg)

    for filepath, entry in sorted(files.items()):
        summary = entry.get("summary", {})
        pct = summary.get("percent_covered", 0.0)
        stmts = summary.get("num_statements", 0)
        miss = summary.get("missing_lines", 0)

        if pct < min_coverage:
            module = filepath.replace("src/perplexity_cli/", "").replace(".py", "")
            failures.append((module, pct, stmts, miss))

    return failures


def main() -> None:
    args = _parse_args()
    coverage_report = _load_report(args.report)
    try:
        failures = _check_modules(coverage_report, args.min_coverage)
    except ValueError as error:
        print(f"Invalid coverage report: {error}", file=sys.stderr)
        sys.exit(2)

    if not failures:
        total_pct = coverage_report.get("totals", {}).get("percent_covered", 0.0)
        file_count = len(coverage_report.get("files", {}))
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
