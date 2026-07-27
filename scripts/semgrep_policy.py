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
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT = 180
SEMGREP_VERSION = "1.171.0"
INSTALL_TIMEOUT = 30

EXIT_CLEAN: int = 0
EXIT_FINDINGS: int = 1
EXIT_MALFORMED: int = 2
EXIT_TIMEOUT: int = 3
EXIT_MISSING_CONFIG: int = 4
EXIT_INTERNAL_ERROR: int = 5

# Semgrep exits 1 when run with ``--error`` and findings are present.
# Any other non-zero code indicates an infrastructure failure.
SEMGREP_FINDINGS_EXIT: int = 1


class PolicyMode(Enum):
    """Select blocking or advisory policy reporting."""

    BLOCKING = "blocking"
    ADVISORY = "advisory"


def _validate_install() -> None:
    """Verify the pinned Semgrep binary is invocable before running scans.

    Wraps the version probe in its own timeout guard so that a hung
    environment cannot crash the wrapper with an uncaught
    ``subprocess.TimeoutExpired``.
    """
    try:
        result = subprocess.run(
            [
                "uvx",
                "--from",
                f"semgrep=={SEMGREP_VERSION}",
                "semgrep",
                "--version",
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=INSTALL_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"Semgrep version probe timed out after {INSTALL_TIMEOUT}s.\n")
        sys.exit(EXIT_INTERNAL_ERROR)
    except OSError as exc:
        sys.stderr.write(f"Failed to invoke Semgrep version probe: {exc}\n")
        sys.exit(EXIT_INTERNAL_ERROR)
    if result.returncode != 0:
        sys.stderr.write(f"Semgrep not available: {result.stderr}\n")
        sys.exit(EXIT_INTERNAL_ERROR)


def _run_semgrep(
    semgrep_args: list[str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """Invoke Semgrep with the canonical JSON flags and return the result."""
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


def _fail_malformed(message: str, result: subprocess.CompletedProcess[str]) -> NoReturn:
    """Write a malformed-output diagnostic and exit with EXIT_MALFORMED."""
    sys.stderr.write(message)
    if result.stderr:
        sys.stderr.write(f"stderr: {result.stderr}\n")
    sys.exit(EXIT_MALFORMED)


def _parse_output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Parse Semgrep stdout as JSON; exit malformed on empty/unparseable output."""
    stdout = result.stdout
    if stdout is None or not stdout.strip():
        _fail_malformed("Semgrep produced empty output.\n", result)
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        _fail_malformed(f"Semgrep produced unparseable JSON: {exc}\n", result)


def _check_errors(semgrep_output: dict[str, Any]) -> None:
    """Exit with internal-error if Semgrep reported any analysis errors."""
    errors = semgrep_output.get("errors", [])
    if errors:
        sys.stderr.write(f"Semgrep reported {len(errors)} analysis error(s):\n")
        for error in errors:
            sys.stderr.write(f"  {error}\n")
        sys.exit(EXIT_INTERNAL_ERROR)


def _fail_internal(message: str) -> NoReturn:
    """Write an internal-error diagnostic and exit with EXIT_INTERNAL_ERROR."""
    sys.stderr.write(message)
    sys.exit(EXIT_INTERNAL_ERROR)


def _register_rule(
    lookup: dict[str, dict[str, Any]],
    rule: dict[str, Any],
) -> None:
    """Validate and insert a single rule entry; fail on any inconsistency."""
    rule_id = rule.get("id")
    if not rule_id:
        _fail_internal("Policy manifest contains a rule without an id.\n")
    if rule_id in lookup:
        _fail_internal(f"Duplicate policy ID '{rule_id}' in policy manifest.\n")
    if "blocking" not in rule:
        _fail_internal(f"Policy entry '{rule_id}' missing 'blocking' attribute.\n")
    lookup[rule_id] = rule


def _load_policy() -> dict[str, dict[str, Any]]:
    """Load the rule policy manifest, failing on missing/duplicate IDs."""
    policy_path = PROJECT_ROOT / "quality" / "semgrep-policy.toml"
    if not policy_path.is_file():
        sys.stderr.write(f"Policy manifest not found: {policy_path}\n")
        sys.exit(EXIT_MISSING_CONFIG)
    try:
        import tomllib

        with open(policy_path, "rb") as handle:
            raw = tomllib.load(handle)
    except Exception as exc:
        sys.stderr.write(f"Failed to load policy manifest: {exc}\n")
        sys.exit(EXIT_INTERNAL_ERROR)
    lookup: dict[str, dict[str, Any]] = {}
    for rule in raw.get("rules", []):
        _register_rule(lookup, rule)
    return lookup


def _classify(
    results: list[dict[str, Any]],
    policy: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split findings into blocking/advisory using the policy manifest.

    Rules registered in the manifest use their declared blocking/advisory
    status. Unknown rule IDs (typically community-pack rules) default to
    blocking to maintain a safe security posture.
    """
    blocking: list[dict[str, Any]] = []
    advisory: list[dict[str, Any]] = []
    for result in results:
        rule_id = result.get("check_id", "")
        rule_policy = policy.get(rule_id)
        is_blocking = rule_policy is None or rule_policy.get("blocking", False)
        if is_blocking:
            blocking.append(result)
        else:
            advisory.append(result)
    return blocking, advisory


def _print_blocking(blocking: list[dict[str, Any]]) -> None:
    """Emit a human-readable summary of blocking findings to stdout."""
    print(f"  Blocking: {len(blocking)} finding(s)")
    for finding in blocking:
        path = finding.get("path", "?")
        start = finding.get("start", {})
        line = start.get("line", 0)
        rule_id = finding.get("check_id", "?")
        print(f"    {path}:{line}  {rule_id}")


def _print_summary(
    all_findings: list[dict[str, Any]],
    blocking: list[dict[str, Any]],
    advisory: list[dict[str, Any]],
) -> None:
    """Print the finding-count summary and per-mode detail blocks."""
    unique_rules = sorted({r.get("check_id", "?") for r in all_findings})
    print(f"Semgrep: {len(all_findings)} finding(s) across {len(unique_rules)} rule(s).")
    if blocking:
        _print_blocking(blocking)
    if advisory:
        print(f"  Advisory: {len(advisory)} finding(s)")


# owner: quality-infrastructure; reason: stable tested helper contract
def _report(  # nosemgrep: boolean-flag-argument
    blocking: list[dict[str, Any]],
    advisory: list[dict[str, Any]],
    is_blocking_mode: bool,
) -> None:
    """Convert the stable boolean contract and print the finding summary."""
    mode = PolicyMode.BLOCKING if is_blocking_mode else PolicyMode.ADVISORY
    _report_for_mode(blocking, advisory, mode)


def _report_for_mode(
    blocking: list[dict[str, Any]],
    advisory: list[dict[str, Any]],
    mode: PolicyMode,
) -> None:
    """Print the overall finding summary to stdout."""
    all_findings = blocking + advisory
    if not all_findings:
        print("Semgrep: no findings.")
        return
    _print_summary(all_findings, blocking, advisory)
    if mode is PolicyMode.ADVISORY:
        print("Running in advisory mode — non-zero exit suppressed.")


def _check_returncode(result: subprocess.CompletedProcess[str]) -> None:
    """Exit with internal-error if Semgrep returned a non-findings code."""
    acceptable = {EXIT_CLEAN, SEMGREP_FINDINGS_EXIT}
    if result.returncode in acceptable:
        return
    sys.stderr.write(f"Semgrep exited with code {result.returncode} (not a findings exit).\n")
    if result.stderr:
        sys.stderr.write(f"stderr: {result.stderr}\n")
    sys.exit(EXIT_INTERNAL_ERROR)


def _run_and_classify(
    semgrep_args: list[str],
    timeout: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run Semgrep, validate output, and apply policy classification.

    Returns the ``(blocking, advisory)`` partition. Exits with the appropriate
    classified code if Semgrep times out, returns a non-findings exit code,
    or emits unparseable/empty/error-laden output.
    """
    try:
        result = _run_semgrep(semgrep_args, timeout)
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"Semgrep timed out after {timeout}s.\n")
        sys.exit(EXIT_TIMEOUT)
    except OSError as exc:
        sys.stderr.write(f"Failed to run Semgrep: {exc}\n")
        sys.exit(EXIT_INTERNAL_ERROR)

    _check_returncode(result)
    semgrep_output = _parse_output(result)
    _check_errors(semgrep_output)

    policy = _load_policy()
    results = semgrep_output.get("results", [])
    return _classify(results, policy)


def main() -> None:
    """Parse args, run Semgrep, classify findings, and exit with status code."""
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
    blocking, advisory = _run_and_classify(semgrep_args, args.timeout)
    _report(blocking, advisory, args.blocking)

    if args.blocking and blocking:
        sys.exit(EXIT_FINDINGS)
    sys.exit(EXIT_CLEAN)


if __name__ == "__main__":
    main()
