"""Semgrep architecture ratchet gate.

Runs the architectural prevention rules in ``.semgrep-architecture.yml``
(targeting the thermo-nuclear review failure modes) and ratchets the findings
against ``quality/baselines/semgrep-architecture.json``.

Existing architectural debt is captured as accepted; the gate fails only on
*new* findings, so the patterns documented in the review cannot spread.

Usage::

    uv run python scripts/check_semgrep_architecture.py [--update-baseline]

Exit codes: 0 = pass, 1 = regression.
"""

from __future__ import annotations

import argparse
import json
import shutil
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
CONFIG = PROJECT_ROOT / ".semgrep-architecture.yml"
BASELINE_NAME = "semgrep-architecture.json"
DESCRIPTION = "Semgrep architecture ratchet: block new structural findings."
_SCRIPT = Path(__file__).name


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    add_update_flag(parser)
    return parser.parse_args()


def _fingerprint(result: dict) -> str:
    start = result.get("start", {})
    return "{}:{}:{}".format(
        result.get("path", "?"),
        start.get("line", 0),
        result.get("check_id", "?"),
    )


def _parse_results(stdout: str, stderr: str) -> list[str]:
    """Parse semgrep JSON output into sorted fingerprints."""
    try:
        data = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        print("Semgrep produced unparseable output:\n" + stderr, file=sys.stderr)
        return []
    return sorted({_fingerprint(r) for r in data.get("results", [])})


def collect_findings() -> list[str]:
    """Run semgrep with the architecture config and return sorted fingerprints."""
    if not CONFIG.is_file():
        print(f"Semgrep architecture config not found: {CONFIG}", file=sys.stderr)
        return []
    cmd = [
        "uvx",
        "semgrep",
        "--config",
        str(CONFIG),
        "--json",
        "--quiet",
        "--metrics=off",
        ".",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=180)
    return _parse_results(result.stdout, result.stderr)


def _report_pass(diff: FingerprintDiff, count: int) -> None:
    print(f"Semgrep architecture ratchet passed: {count} baselined finding(s); no new findings.")
    if diff.removed:
        print(
            f"Improvement: {len(diff.removed)} finding(s) cleared "
            "(run with --update-baseline to capture)."
        )


def _report_regression(diff: FingerprintDiff) -> int:
    print("Semgrep architecture ratchet FAILED: new findings.\n", file=sys.stderr)
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
        print(f"Semgrep architecture baseline refreshed: {len(current)} finding(s) -> {path}")
        return

    diff = diff_fingerprints(current, load_fingerprints(BASELINE_NAME))
    if diff.is_regression:
        sys.exit(_report_regression(diff))
    _report_pass(diff, len(current))


if __name__ == "__main__":
    main()
