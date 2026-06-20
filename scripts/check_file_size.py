"""File-size ratchet gate.

Fails when a source file exceeds the line cap (default 1000), or when a
previously-baselined oversized file grows.  Existing oversized files are
captured in ``quality/baselines/file-size.json`` as accepted debt so the gate
blocks *new* sprawl (and growth of known sprawl) without forcing a refactor.

Usage::

    uv run python scripts/check_file_size.py [--max-lines 1000] [--update-baseline]

Exit codes: 0 = pass, 1 = regression, 2 = usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ratchet import (
    CountDiff,
    add_update_flag,
    diff_counts,
    load_counts,
    save_counts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
DEFAULT_MAX_LINES = 1000
BASELINE_NAME = "file-size.json"
DESCRIPTION = "File-size ratchet: block new or grown oversized source files."
_SCRIPT = Path(__file__).name


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(
        "--max-lines",
        type=int,
        default=DEFAULT_MAX_LINES,
        help=f"Line cap per source file (default: {DEFAULT_MAX_LINES}).",
    )
    add_update_flag(parser)
    return parser.parse_args()


def collect_oversized(max_lines: int) -> dict[str, int]:
    """Return ``{relative_path: line_count}`` for source files over the cap."""
    oversized: dict[str, int] = {}
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        with path.open("rb") as handle:
            line_count = sum(1 for _ in handle)
        if line_count > max_lines:
            oversized[str(path.relative_to(PROJECT_ROOT))] = line_count
    return oversized


def _report_pass(diff: CountDiff, max_lines: int, current_count: int) -> None:
    """Print the passing summary plus any shrinkage worth capturing."""
    print(
        f"File-size ratchet passed: {current_count} baselined oversized file(s), "
        f"cap {max_lines}; no new or grown files."
    )
    if diff.shrunk:
        print("Shrinkage detected (run with --update-baseline to capture):")
        for file, (prev, now) in diff.shrunk.items():
            print(f"  {file}: {prev} -> {now}")


def _report_regression(diff: CountDiff, max_lines: int) -> int:
    """Print the regression report and return the exit code."""
    print("File-size ratchet FAILED: new or grown oversized files.\n", file=sys.stderr)
    for file, count in diff.new.items():
        print(f"  NEW      {file}: {count} lines (cap {max_lines})", file=sys.stderr)
    for file, (prev, now) in diff.grown.items():
        print(f"  GREW     {file}: {prev} -> {now} lines", file=sys.stderr)
    print(
        "\nSplit the file, or refresh the baseline if the growth is intentional:\n"
        f"  uv run python scripts/{_SCRIPT} --update-baseline",
        file=sys.stderr,
    )
    return 1


def main() -> None:
    args = _parse_args()
    current = collect_oversized(args.max_lines)

    if args.update_baseline:
        path = save_counts(BASELINE_NAME, current)
        print(
            f"File-size baseline refreshed: {len(current)} file(s) over {args.max_lines} -> {path}"
        )
        return

    diff = diff_counts(current, load_counts(BASELINE_NAME))
    if diff.is_regression:
        sys.exit(_report_regression(diff, args.max_lines))
    _report_pass(diff, args.max_lines, len(current))


if __name__ == "__main__":
    main()
