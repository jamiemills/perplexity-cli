"""Canonical Semgrep wrapper with policy enforcement.

Runs Semgrep, validates JSON output, applies the rule policy manifest, and
returns a classified exit code. Supports ``--blocking`` and ``--advisory``
modes. Used by every canonical blocking and advisory target.

Usage::

    uv run python scripts/semgrep_policy.py --blocking [configs...]
    uv run python scripts/semgrep_policy.py --advisory  [configs...]

Semgrep arguments are restricted to the declared invocation schema: repeated
configs, severities and excludes, optional JSON/SARIF output paths, and targets.

Exit codes (classified):
    0 — clean: no blocking findings
    1 — findings: blocking findings detected
    2 — malformed: Semgrep JSON unparseable
    3 — timeout: Semgrep process timed out
    4 — missing-config: required config file not found
    5 — internal-error: invocation contract failure, unexpected failure, or
        Semgrep errors array
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404  # owner: quality-infrastructure; reason: pinned Semgrep runs as validated argv without a shell
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn, cast

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


class SemgrepInvocationError(ValueError):
    """The requested Semgrep invocation is outside the supported schema."""


class _InvocationParser(argparse.ArgumentParser):
    """Argument parser that reports errors through policy classification."""

    def error(self, message: str) -> NoReturn:
        raise SemgrepInvocationError(message)


@dataclass(frozen=True, slots=True)
class SemgrepInvocation:
    """Validated Semgrep scanner arguments."""

    configs: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    json_outputs: tuple[str, ...] = ()
    sarif_outputs: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()

    def to_argv(self) -> list[str]:
        """Render the validated invocation as Semgrep argv."""
        argv: list[str] = []
        _append_options(argv, "--config", self.configs)
        _append_options(argv, "--severity", self.severities)
        _append_options(argv, "--exclude", self.excludes)
        _append_options(argv, "--json-output", self.json_outputs)
        _append_options(argv, "--sarif-output", self.sarif_outputs)
        argv.extend(self.targets)
        return argv


def _append_options(argv: list[str], option: str, values: tuple[str, ...]) -> None:
    """Append repeated option/value pairs to argv."""
    for value in values:
        argv.extend((option, value))


def _validate_install() -> None:
    """Verify the pinned Semgrep binary is invocable before running scans.

    Wraps the version probe in its own timeout guard so that a hung
    environment cannot crash the wrapper with an uncaught
    ``subprocess.TimeoutExpired``.
    """
    try:
        result = subprocess.run(  # nosec B603 B607  # owner: quality-infrastructure; reason: fixed pinned Semgrep version probe runs without a shell
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
    invocation = _parse_semgrep_invocation(semgrep_args)
    _validate_timeout(timeout)
    cmd = [
        "uvx",
        "--from",
        f"semgrep=={SEMGREP_VERSION}",
        "semgrep",
        *invocation.to_argv(),
        "--json",
        "--quiet",
        "--metrics=off",
    ]
    return subprocess.run(  # nosec B603  # owner: quality-infrastructure; reason: all forwarded argv passed the typed Semgrep invocation schema
        cmd,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=timeout,
        check=False,
    )


def _scanner_parser() -> argparse.ArgumentParser:
    """Build the fail-closed parser for supported Semgrep arguments."""
    parser = _InvocationParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--config", action="append", default=[])
    parser.add_argument(
        "--severity", action="append", choices=("ERROR", "WARNING", "INFO"), default=[]
    )
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--json-output", action="append", default=[])
    parser.add_argument("--sarif-output", action="append", default=[])
    parser.add_argument("targets", nargs="*")
    return parser


def _parse_semgrep_invocation(semgrep_args: list[str]) -> SemgrepInvocation:
    """Parse supported scanner arguments into a typed invocation."""
    args = _scanner_parser().parse_args(semgrep_args)
    values = (*args.config, *args.exclude, *args.json_output, *args.sarif_output, *args.targets)
    if any(not _safe_argv_value(value) for value in values):
        msg = "Semgrep argument values must be non-empty and free of control characters."
        raise SemgrepInvocationError(msg)
    return SemgrepInvocation(
        configs=tuple(args.config),
        severities=tuple(args.severity),
        excludes=tuple(args.exclude),
        json_outputs=tuple(args.json_output),
        sarif_outputs=tuple(args.sarif_output),
        targets=tuple(args.targets),
    )


def _safe_argv_value(value: str) -> bool:
    """Return whether a scanner argument is safe as one non-option argv value."""
    return (
        bool(value)
        and not value.startswith("-")
        and not any(character in value for character in ("\x00", "\n", "\r"))
    )


def _validate_timeout(timeout: int) -> None:
    """Reject non-positive scanner timeouts through invocation classification."""
    if timeout <= 0:
        msg = "timeout must be greater than zero"
        raise SemgrepInvocationError(msg)


def _fail_malformed(message: str, result: subprocess.CompletedProcess[str]) -> NoReturn:
    """Write a malformed-output diagnostic and exit with EXIT_MALFORMED."""
    sys.stderr.write(message)
    if result.stderr:
        sys.stderr.write(f"stderr: {result.stderr}\n")
    sys.exit(EXIT_MALFORMED)


def _parse_output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Parse Semgrep stdout as JSON; exit malformed on empty/unparseable output."""
    stdout = cast(object, result.stdout)
    if stdout is None or not isinstance(stdout, str) or not stdout.strip():
        _fail_malformed("Semgrep produced empty output.\n", result)
    try:
        decoded: object = json.loads(stdout)
    except json.JSONDecodeError as exc:
        _fail_malformed(f"Semgrep produced unparseable JSON: {exc}\n", result)
    if not isinstance(decoded, dict):
        _fail_malformed("Semgrep JSON root must be an object.\n", result)
    return cast(dict[str, Any], decoded)


def _check_errors(semgrep_output: dict[str, Any]) -> None:
    """Exit with internal-error if Semgrep reported any analysis errors."""
    errors = _require_list_field(semgrep_output, "errors")
    if errors:
        sys.stderr.write(f"Semgrep reported {len(errors)} analysis error(s):\n")
        for error in errors:
            sys.stderr.write(f"  {error}\n")
        sys.exit(EXIT_INTERNAL_ERROR)


def _require_list_field(semgrep_output: dict[str, Any], field_name: str) -> list[object]:
    """Return a list field or classify the scanner output as malformed."""
    value: object = semgrep_output.get(field_name, [])
    if not isinstance(value, list):
        sys.stderr.write(f"Semgrep JSON field '{field_name}' must be a list.\n")
        sys.exit(EXIT_MALFORMED)
    return cast(list[object], value)


def _results_from_output(semgrep_output: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate and return Semgrep result objects."""
    results = _require_list_field(semgrep_output, "results")
    if any(not isinstance(result, dict) for result in results):
        sys.stderr.write("Semgrep JSON field 'results' must contain only objects.\n")
        sys.exit(EXIT_MALFORMED)
    return [cast(dict[str, Any], result) for result in results]


def _fail_internal(message: str) -> NoReturn:
    """Write an internal-error diagnostic and exit with EXIT_INTERNAL_ERROR."""
    sys.stderr.write(message)
    sys.exit(EXIT_INTERNAL_ERROR)


def _fail_invocation(error: SemgrepInvocationError) -> NoReturn:
    """Report an invocation contract failure as an internal/config error."""
    _fail_internal(f"Invalid Semgrep invocation: {error}\n")


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


def _report(  # nosemgrep: boolean-flag-argument  # owner: quality-infrastructure; reason: stable tested helper contract
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
    except SemgrepInvocationError as exc:
        _fail_invocation(exc)
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
    results = _results_from_output(semgrep_output)
    return _classify(results, policy)


def main() -> None:
    """Parse args, run Semgrep, classify findings, and exit with status code."""
    parser = _InvocationParser(
        description="Canonical Semgrep wrapper with policy enforcement.", allow_abbrev=False
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
    parser.add_argument("--config", action="append", default=[])
    parser.add_argument(
        "--severity", action="append", choices=("ERROR", "WARNING", "INFO"), default=[]
    )
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--json-output", action="append", default=[])
    parser.add_argument("--sarif-output", action="append", default=[])
    parser.add_argument("targets", nargs="*")
    try:
        args = parser.parse_args()
    except SemgrepInvocationError as exc:
        _fail_invocation(exc)
    invocation = SemgrepInvocation(
        configs=tuple(args.config),
        severities=tuple(args.severity),
        excludes=tuple(args.exclude),
        json_outputs=tuple(args.json_output),
        sarif_outputs=tuple(args.sarif_output),
        targets=tuple(args.targets),
    )
    try:
        _parse_semgrep_invocation(invocation.to_argv())
        _validate_timeout(args.timeout)
    except SemgrepInvocationError as exc:
        _fail_invocation(exc)

    _validate_install()
    blocking, advisory = _run_and_classify(invocation.to_argv(), args.timeout)
    _report(blocking, advisory, args.blocking)

    if args.blocking and blocking:
        sys.exit(EXIT_FINDINGS)
    sys.exit(EXIT_CLEAN)


if __name__ == "__main__":
    main()
