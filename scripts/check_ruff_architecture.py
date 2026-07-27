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

# Ruff exit codes: 0 = no findings, 1 = findings present, >=2 = tool error.
_TOOL_ERROR_EXIT_THRESHOLD = 2

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


def _fingerprint(diagnostic: dict) -> str:
    """Create a stable identifier from a Ruff JSON diagnostic."""
    location = diagnostic.get("location", {})
    filename = diagnostic.get("filename", "?")
    root_prefix = str(PROJECT_ROOT) + "/"
    if isinstance(filename, str) and filename.startswith(root_prefix):
        filename = filename[len(root_prefix) :]
    return "{}:{}:{}".format(
        filename,
        location.get("row", 0),
        diagnostic.get("code", "?"),
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
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=120,
        check=False,
    )
    # Ruff exits 0 = no findings, 1 = findings, 2+ = tool error.
    # All three are valid for JSON parsing; only exit >=2 is a tool failure.
    is_tool_error = (
        result.returncode >= _TOOL_ERROR_EXIT_THRESHOLD if result.returncode is not None else False
    )
    try:
        items = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        detail = result.stderr.strip() or "Ruff produced unparseable output."
        raise RuntimeError(detail) from exc
    if is_tool_error:
        raise RuntimeError(result.stderr.strip() or f"Ruff exited with status {result.returncode}.")
    return sorted({_fingerprint(item) for item in items})


def _report_pass(diff: FingerprintDiff, count: int) -> None:
    """Print a passing summary with optional shrinkage note."""
    print(f"Ruff architecture ratchet passed: {count} baselined finding(s); no new findings.")
    if diff.removed:
        print(
            f"Improvement: {len(diff.removed)} finding(s) cleared "
            "(run with --update-baseline to capture)."
        )


def _report_regression(diff: FingerprintDiff) -> int:
    """Print a regression report and return exit code 1."""
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
    """Entry point: collect findings, ratchet, and report."""
    args = _parse_args()
    try:
        current = collect_findings()
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Ruff architecture gate could not run: {exc}", file=sys.stderr)
        sys.exit(2)

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
