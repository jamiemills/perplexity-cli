"""Semgrep architecture ratchet gate.

Runs the structural prevention rules (now consolidated in ``.semgrep.yml``)
and ratchets the findings against
``quality/baselines/semgrep-architecture.json``.

Existing architectural debt is captured as accepted; the gate fails only on
*new* findings, so the patterns documented in the review cannot spread.

Usage::

    uv run python scripts/check_semgrep_architecture.py [--update-baseline]

Exit codes: 0 = pass, 1 = regression, 2 = internal error.
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
CONFIG = PROJECT_ROOT / ".semgrep.yml"
BASELINE_NAME = "semgrep-architecture.json"
DESCRIPTION = "Semgrep architecture ratchet: block new structural findings."
_SCRIPT = Path(__file__).name
SEMGREP_VERSION = "1.171.0"

ARCH_RULE_IDS: frozenset[str] = frozenset(
    {
        "function-local-import",
        "retry-sleep-outside-canonical",
        "ad-hoc-http-status-classification",
        "sys-exit-outside-boundary",
        "http-client-outside-transport",
        "write-then-chmod-toctou",
        "getter-with-side-effects",
        "click-echo-outside-presentation",
    }
)


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
    try:
        semgrep_payload = json.loads(stdout or "{}")
    except json.JSONDecodeError as error:
        message = stderr.strip() or "Semgrep produced unparseable JSON output."
        raise RuntimeError(message) from error
    errors = semgrep_payload.get("errors", [])
    if errors:
        raise RuntimeError(f"Semgrep reported analysis errors: {errors}")
    results = semgrep_payload.get("results", [])
    arch_results = [r for r in results if r.get("check_id") in ARCH_RULE_IDS]
    return sorted({_fingerprint(r) for r in arch_results})


def collect_findings() -> list[str]:
    """Run semgrep with the canonical config and return sorted architecture fingerprints."""
    if not CONFIG.is_file():
        raise RuntimeError(f"Semgrep config not found: {CONFIG}")
    cmd = [
        "uvx",
        "--from",
        f"semgrep=={SEMGREP_VERSION}",
        "semgrep",
        "--config",
        str(CONFIG),
        "--json",
        "--quiet",
        "--metrics=off",
        ".",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"Semgrep exited with status {result.returncode}."
        raise RuntimeError(detail)
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
    try:
        current = collect_findings()
    except RuntimeError as exc:
        print(f"Semgrep architecture gate could not run: {exc}", file=sys.stderr)
        sys.exit(2)

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
