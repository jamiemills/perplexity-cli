"""Canonical Semgrep wrapper with policy enforcement.

Runs Semgrep, validates JSON output, applies the rule policy manifest, and
returns a classified exit code. Supports ``--blocking`` and ``--advisory``
modes. Used by every canonical blocking and advisory target.

Usage::

    uv run python scripts/semgrep_policy.py --blocking [configs...]
    uv run python scripts/semgrep_policy.py --advisory  [configs...]

All additional arguments after the mode flag are forwarded to Semgrep as-is
(configs, severity, excludes, targets, etc.).

Exit codes (classified):
    0 — clean: no blocking findings
    1 — findings: blocking findings detected
    2 — malformed: Semgrep JSON unparseable
    3 — timeout: Semgrep process timed out
    4 — missing-config: required config file not found
    5 — internal-error: unexpected failure or Semgrep errors array
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT = 180
SEMGREP_VERSION = "1.171.0"

EXIT_CLEAN: int = 0
EXIT_FINDINGS: int = 1
EXIT_MALFORMED: int = 2
EXIT_TIMEOUT: int = 3
EXIT_MISSING_CONFIG: int = 4
EXIT_INTERNAL_ERROR: int = 5


def _validate_install() -> None:
    result = subprocess.run(
        ["uvx", "--from", f"semgrep=={SEMGREP_VERSION}", "semgrep", "--version"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(f"Semgrep not available: {result.stderr}\n")
        sys.exit(EXIT_INTERNAL_ERROR)


def _run_semgrep(
    semgrep_args: list[str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "uvx",
        "--from",
        f"semgrep=={SEMGREP_VERSION}",
        "semgrep",
        *semgrep_args,
        "--json",
        "--quiet",
        "--metrics=off",
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=timeout,
        check=False,
    )


def _parse_output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"Semgrep produced unparseable JSON: {exc}\n")
        if result.stderr:
            sys.stderr.write(f"stderr: {result.stderr}\n")
        sys.exit(EXIT_MALFORMED)


def _check_errors(data: dict[str, Any]) -> None:
    errors = data.get("errors", [])
    if errors:
        sys.stderr.write(f"Semgrep reported {len(errors)} analysis error(s):\n")
        for error in errors:
            sys.stderr.write(f"  {error}\n")
        sys.exit(EXIT_INTERNAL_ERROR)


def _load_policy() -> dict[str, dict[str, Any]]:
    policy_path = PROJECT_ROOT / "quality" / "semgrep-policy.toml"
    if not policy_path.is_file():
        sys.stderr.write(f"Policy manifest not found: {policy_path}\n")
        sys.exit(EXIT_MISSING_CONFIG)
    try:
        import tomllib

        with open(policy_path, "rb") as f:
            raw = tomllib.load(f)
    except Exception as exc:
        sys.stderr.write(f"Failed to load policy manifest: {exc}\n")
        sys.exit(EXIT_INTERNAL_ERROR)
    lookup: dict[str, dict[str, Any]] = {}
    for rule in raw.get("rules", []):
        lookup[rule["id"]] = rule
    return lookup


def _classify(
    results: list[dict[str, Any]],
    policy: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocking: list[dict[str, Any]] = []
    advisory: list[dict[str, Any]] = []
    for result in results:
        rule_id = result.get("check_id", "")
        rule_policy = policy.get(rule_id, {})
        is_blocking = rule_policy.get("blocking", True)
        if is_blocking:
            blocking.append(result)
        else:
            advisory.append(result)
    return blocking, advisory


def _print_blocking(blocking: list[dict[str, Any]]) -> None:
    print("  Blocking: %s finding(s)", len(blocking))
    for finding in blocking:
        path = finding.get("path", "?")
        start = finding.get("start", {})
        line = start.get("line", 0)
        rule_id = finding.get("check_id", "?")
        print("    %s:%s  %s", path, line, rule_id)


def _report(
    blocking: list[dict[str, Any]],
    advisory: list[dict[str, Any]],
    is_blocking_mode: bool,
) -> None:
    all_findings = blocking + advisory
    if not all_findings:
        print("Semgrep: no findings.")
        return
    unique_rules = sorted({r.get("check_id", "?") for r in all_findings})
    print(
        "Semgrep: %s finding(s) across %s rule(s).",
        len(all_findings),
        len(unique_rules),
    )
    if blocking:
        _print_blocking(blocking)
    if advisory:
        print("  Advisory: %s finding(s)", len(advisory))
    if not is_blocking_mode:
        print("Running in advisory mode — non-zero exit suppressed.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Canonical Semgrep wrapper with policy enforcement."
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--blocking", action="store_true", help="Fail on blocking findings (CI gate)."
    )
    mode_group.add_argument(
        "--advisory", action="store_true", help="Report all findings but never fail."
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Process timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    args, semgrep_args = parser.parse_known_args()

    _validate_install()

    try:
        result = _run_semgrep(semgrep_args, args.timeout)
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"Semgrep timed out after {args.timeout}s.\n")
        sys.exit(EXIT_TIMEOUT)
    except OSError as exc:
        sys.stderr.write(f"Failed to run Semgrep: {exc}\n")
        sys.exit(EXIT_INTERNAL_ERROR)

    data = _parse_output(result)
    _check_errors(data)

    policy = _load_policy()
    results = data.get("results", [])
    blocking, advisory = _classify(results, policy)
    _report(blocking, advisory, args.blocking)

    if args.blocking and blocking:
        sys.exit(EXIT_FINDINGS)
    sys.exit(EXIT_CLEAN)


if __name__ == "__main__":
    main()
