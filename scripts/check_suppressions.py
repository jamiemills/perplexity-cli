"""Suppression ratchet gate.

Counts inline analyser-suppression comments in ``src/`` (``# noqa``,
``# nosemgrep``, ``# nosec``, ``# type: ignore``, ``# pyright: ignore``) per
file and fails when the total grows or appears in a new file.  Current
suppressions are captured in ``quality/baselines/suppressions.json`` as
accepted debt, blocking new "just silence the linter" behaviour without
forcing removal of existing suppressions.

Usage::

    uv run python scripts/check_suppressions.py [--update-baseline]

Exit codes: 0 = pass, 1 = regression.
"""

from __future__ import annotations

import argparse
import re
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
BASELINE_NAME = "suppressions.json"
DESCRIPTION = "Suppression ratchet: block new or grown inline suppressions."
_SCRIPT = Path(__file__).name

# Matches any inline suppression marker on a source line.  Anchored to the
# comment start so legitimate identifiers like ``ignore_exceptions`` do not match.
_SUPPRESSION_RE = re.compile(
    r"#\s*(noqa\b|nosemgrep\b|nosec\b|type:\s*ignore\b|pyright:\s*ignore\b)",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    add_update_flag(parser)
    return parser.parse_args()


def collect_suppressions() -> dict[str, int]:
    """Return ``{relative_path: count}`` of suppression markers in src/."""
    counts: dict[str, int] = {}
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        total = sum(1 for _ in _SUPPRESSION_RE.finditer(text))
        if total:
            counts[str(path.relative_to(PROJECT_ROOT))] = total
    return counts


def _report_pass(diff: CountDiff, file_count: int) -> None:
    print(
        f"Suppression ratchet passed: {diff.current_total} suppression(s) across "
        f"{file_count} baselined file(s); no growth."
    )
    if diff.shrunk:
        print("Shrinkage detected (run with --update-baseline to capture):")
        for file, (prev, now) in diff.shrunk.items():
            print(f"  {file}: {prev} -> {now}")


def _report_regression(diff: CountDiff) -> int:
    print("Suppression ratchet FAILED: new or grown suppressions.\n", file=sys.stderr)
    for file, count in diff.new.items():
        print(f"  NEW    {file}: {count} suppression(s)", file=sys.stderr)
    for file, (prev, now) in diff.grown.items():
        print(f"  GREW   {file}: {prev} -> {now}", file=sys.stderr)
    print(
        "\nFix the underlying finding, or justify and refresh the baseline:\n"
        f"  uv run python scripts/{_SCRIPT} --update-baseline",
        file=sys.stderr,
    )
    return 1


def main() -> None:
    args = _parse_args()
    current = collect_suppressions()

    if args.update_baseline:
        path = save_counts(BASELINE_NAME, current)
        print(f"Suppression baseline refreshed: {sum(current.values())} -> {path}")
        return

    diff = diff_counts(current, load_counts(BASELINE_NAME))
    if diff.is_regression:
        sys.exit(_report_regression(diff))
    _report_pass(diff, len(current))


if __name__ == "__main__":
    main()
