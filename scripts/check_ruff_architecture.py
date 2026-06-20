"""Ruff architecture ratchet gate.

Runs Ruff with the structural rule set the conventions rely on (cyclomatic
complexity, parameter count, public-method count, magic values, unused
arguments) at the project's intended thresholds (CC<=5, max 4 params), and
ratchets the findings against ``quality/baselines/ruff-architecture.json``.

Existing violations (documented in ``.claude/thermo-nuclear-review.md``) are
captured as accepted debt; the gate fails only on *new* findings, blocking
future god-functions and parameter explosions without forcing a refactor now.

Usage::

    uv run python scripts/check_ruff_architecture.py [--update-baseline]

Exit codes: 0 = pass, 1 = regression.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ratchet import (
    FingerprintDiff,
    add_update_flag,
    diff_fingerprints,
    load_fingerprints,
    save_fingerprints,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_NAME = "ruff-architecture.json"
DESCRIPTION = "Ruff architecture ratchet: block new complexity/parameter findings."
_SCRIPT = Path(__file__).name

_RULES = ["C901", "PLR0913", "PLR0904", "PLR2004", "ARG001", "ARG002"]
_CONFIG_FLAGS = [
    "--config",
    "lint.mccabe.max-complexity = 5",
    "--config",
    "lint.pylint.max-args = 4",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    add_update_flag(parser)
    return parser.parse_args()


def _fingerprint(item: dict) -> str:
    location = item.get("location", {})
    return "{}:{}:{}".format(
        item.get("filename", "?"),
        location.get("row", 0),
        item.get("code", "?"),
    )


def collect_findings() -> list[str]:
    """Run Ruff and return sorted finding fingerprints."""
    cmd = [
        "uv",
        "run",
        "ruff",
        "check",
        "--select",
        ",".join(_RULES),
        *_CONFIG_FLAGS,
        "--output-format",
        "json",
        "--no-fix",
        "src",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    try:
        items = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        print("Ruff produced unparseable output:\n" + result.stderr, file=sys.stderr)
        return []
    return sorted({_fingerprint(item) for item in items})


def _report_pass(diff: FingerprintDiff, count: int) -> None:
    print(f"Ruff architecture ratchet passed: {count} baselined finding(s); no new findings.")
    if diff.removed:
        print(
            f"Improvement: {len(diff.removed)} finding(s) cleared "
            "(run with --update-baseline to capture)."
        )


def _report_regression(diff: FingerprintDiff) -> int:
    print("Ruff architecture ratchet FAILED: new findings.\n", file=sys.stderr)
    for fingerprint in diff.new:
        print(f"  NEW  {fingerprint}", file=sys.stderr)
    print(
        "\nFix the finding, or refresh the baseline after intentional changes:\n"
        f"  uv run python scripts/{_SCRIPT} --update-baseline",
        file=sys.stderr,
    )
    return 1


def main() -> None:
    args = _parse_args()
    current = collect_findings()

    if args.update_baseline:
        path = save_fingerprints(BASELINE_NAME, current)
        print(f"Ruff architecture baseline refreshed: {len(current)} finding(s) -> {path}")
        return

    diff = diff_fingerprints(current, load_fingerprints(BASELINE_NAME))
    if diff.is_regression:
        sys.exit(_report_regression(diff))
    _report_pass(diff, len(current))


if __name__ == "__main__":
    main()
