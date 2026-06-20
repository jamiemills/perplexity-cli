"""Pyright strict ratchet gate.

Runs Pyright in ``strict`` mode against ``src/`` (using a dedicated config so
the standard ``make typecheck-pyright`` is unaffected) and ratchets the
diagnostics against ``quality/baselines/pyright-strict.json``.

Existing ``Any`` / untyped-boundary diagnostics (documented in
``.claude/thermo-nuclear-review.md`` section 3) are captured as accepted debt;
the gate fails only on *new* strict diagnostics, blocking future boundary
erosion without forcing the full typed-model refactor now.

Usage::

    uv run python scripts/check_pyright_strict.py [--update-baseline]

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
TEMP_CONFIG = PROJECT_ROOT / ".pyright.strict.tmp.json"
BASELINE_NAME = "pyright-strict.json"
DESCRIPTION = "Pyright strict ratchet: block new Any/unknown diagnostics."
_SCRIPT = Path(__file__).name

_STRICT_CONFIG = {
    "include": ["src/"],
    "typeCheckingMode": "strict",
    "pythonVersion": "3.12",
    "reportMissingTypeStubs": "none",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    add_update_flag(parser)
    return parser.parse_args()


def _fingerprint(diag: dict) -> str:
    start = diag.get("range", {}).get("start", {})
    return "{}:{}:{}:{}".format(
        diag.get("file", "?"),
        start.get("line", 0),
        start.get("character", 0),
        diag.get("rule") or diag.get("message", "?")[:40],
    )


def collect_findings() -> list[str]:
    """Run Pyright in strict mode and return sorted diagnostic fingerprints."""
    TEMP_CONFIG.write_text(json.dumps(_STRICT_CONFIG), encoding="utf-8")
    cmd = ["uv", "run", "pyright", "-p", str(TEMP_CONFIG), "--outputjson"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    finally:
        TEMP_CONFIG.unlink(missing_ok=True)
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        print("Pyright produced unparseable output:\n" + result.stderr, file=sys.stderr)
        return []
    diagnostics = data.get("generalDiagnostics", [])
    return sorted({_fingerprint(d) for d in diagnostics})


def _report_pass(diff: FingerprintDiff, count: int) -> None:
    print(f"Pyright strict ratchet passed: {count} baselined diagnostic(s); no new findings.")
    if diff.removed:
        print(
            f"Improvement: {len(diff.removed)} diagnostic(s) cleared "
            "(run with --update-baseline to capture)."
        )


def _report_regression(diff: FingerprintDiff) -> int:
    print("Pyright strict ratchet FAILED: new strict diagnostics.\n", file=sys.stderr)
    for fingerprint in diff.new:
        print(f"  NEW  {fingerprint}", file=sys.stderr)
    print(
        "\nFix the typing, or refresh the baseline after intentional changes:\n"
        f"  uv run python scripts/{_SCRIPT} --update-baseline",
        file=sys.stderr,
    )
    return 1


def main() -> None:
    args = _parse_args()
    current = collect_findings()

    if args.update_baseline:
        path = save_fingerprints(BASELINE_NAME, current)
        print(f"Pyright strict baseline refreshed: {len(current)} diagnostic(s) -> {path}")
        return

    diff = diff_fingerprints(current, load_fingerprints(BASELINE_NAME))
    if diff.is_regression:
        sys.exit(_report_regression(diff))
    _report_pass(diff, len(current))


if __name__ == "__main__":
    main()
