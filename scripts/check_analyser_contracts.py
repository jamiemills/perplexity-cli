"""Check analyser behaviour against declared contracts.

Validates ``quality/analyser-contracts.toml`` and then runs each
non-pending analyser through its canonical Make target, verifying that
the observed exit code matches a declared state.

Usage::

    uv run python scripts/check_analyser_contracts.py            # validate + run
    uv run python scripts/check_analyser_contracts.py --validate # schema-only
    uv run python scripts/check_analyser_contracts.py --run      # run non-pending
    uv run python scripts/check_analyser_contracts.py --pending-ok
    uv run python scripts/check_analyser_contracts.py --json

Exit codes: 0 = all contracts honoured, 1 = unexpected exit detected,
2 = schema/inventory validation failure, 3 = usage/invocation error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONTRACTS = _PROJECT_ROOT / "quality" / "analyser-contracts.toml"

_EXIT_ALL_PASS = 0
_EXIT_CONTRACT_BREACH = 1
_EXIT_SCHEMA_FAIL = 2
_EXIT_USAGE = 3

_REQUIRED_ANALYSER_KEYS = frozenset({"id", "target", "phase", "status", "description", "states"})
_VALID_STATUSES = frozenset({"active", "pending", "retired"})
_REQUIRED_STATES = frozenset({"clean"})
_VALID_STATE_KEYS = frozenset({"exit_min", "exit_max", "signal"})


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateContract:
    """Expected exit-code range and optional signal for one outcome."""

    name: str
    exit_min: int
    exit_max: int
    signal: str | None = None

    def matches(self, exit_code: int, signal_name: str | None) -> bool:
        """Return True when *exit_code* and *signal_name* satisfy this contract."""
        if signal_name is None and self.signal is None:
            return self.exit_min <= exit_code <= self.exit_max
        if signal_name is None or self.signal is None:
            return False
        return signal_name == self.signal and self.exit_min <= exit_code <= self.exit_max


@dataclass(frozen=True, slots=True)
class AnalyserContract:
    """A single analyser's full contract from the inventory."""

    id: str
    target: str
    phase: int
    status: str
    description: str
    states: dict[str, StateContract]
    test_node_ids: tuple[str, ...] = ()


@dataclass
class ContractResult:
    """Outcome of running one analyser against its contract."""

    analyser_id: str
    target: str
    exit_code: int
    signal_name: str | None
    matched_state: str | None
    duration_s: float
    expected: bool
    stdout_snippet: str = ""
    stderr_snippet: str = ""
    declared_states: str = ""

    @property
    def passed(self) -> bool:
        return self.expected


@dataclass
class RunReport:
    """Aggregated report for an entire contract-check run."""

    results: list[ContractResult] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    skipped_pending: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def all_contracts_honoured(self) -> bool:
        return all(result.passed for result in self.results) and not self.schema_errors


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------


def _try_import_tomllib() -> Any:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    return tomllib


def _check_schema_section(contracts_document: dict[str, Any]) -> list[str]:
    """Validate the [schema] section of the TOML file."""
    schema = contracts_document.get("schema")
    if not isinstance(schema, dict):
        return ["Missing or invalid [schema] section"]
    if schema.get("version") != 1:
        return [f"Unsupported schema version {schema.get('version')}"]
    return []


def _check_analysers_array(contracts_document: dict[str, Any]) -> list[str]:
    """Validate the [[analysers]] array exists and is non-empty."""
    analyser_entries = contracts_document.get("analysers")
    if analyser_entries is None:
        return ["Missing [[analysers]] array"]
    if not isinstance(analyser_entries, list):
        return ["[[analysers]] must be an array of tables"]
    if not analyser_entries:
        return ["[[analysers]] array is empty"]
    return []


def load_contracts(path: Path) -> tuple[list[AnalyserContract], list[str]]:
    """Parse the contracts TOML file.

    Returns:
        A tuple of (contracts, schema_errors).
    """
    tomllib = _try_import_tomllib()
    try:
        with path.open("rb") as fh:
            contracts_document = tomllib.load(fh)
    except FileNotFoundError:
        return [], [f"Contracts file not found: {path}"]
    except Exception as exc:
        return [], [f"Failed to parse TOML: {exc}"]

    errors: list[str] = []
    errors.extend(_check_schema_section(contracts_document))
    errors.extend(_check_analysers_array(contracts_document))
    if errors:
        return [], errors

    raw_analysers = contracts_document["analysers"]
    return _parse_all_analysers(raw_analysers, errors)


def _parse_all_analysers(
    raw: list[Any], errors: list[str]
) -> tuple[list[AnalyserContract], list[str]]:
    """Parse every entry in the [[analysers]] array."""
    contracts: list[AnalyserContract] = []
    for idx, entry in enumerate(raw):
        contract, entry_errors = _parse_single_analyser(entry, idx)
        errors.extend(entry_errors)
        if contract is not None:
            contracts.append(contract)
    _check_duplicate_ids(contracts, errors)
    return contracts, errors


def _validate_required_keys(entry: dict[str, Any], idx: int) -> list[str]:
    """Check that all required top-level keys are present."""
    prefix = f"analysers[{idx}]"
    missing = _REQUIRED_ANALYSER_KEYS - set(entry.keys())
    if missing:
        return [f"{prefix}: missing required keys: {', '.join(sorted(missing))}"]
    return []


def _check_field_id(entry: dict[str, Any], prefix: str, errors: list[str]) -> None:
    """Validate the 'id' field."""
    if not isinstance(entry.get("id"), str) or not entry.get("id"):
        errors.append(f"{prefix}: 'id' must be a non-empty string")


def _check_field_target(entry: dict[str, Any], prefix: str, errors: list[str]) -> None:
    """Validate the 'target' field."""
    if not isinstance(entry.get("target"), str) or not entry.get("target"):
        errors.append(f"{prefix}: 'target' must be a non-empty string")


def _check_field_phase(entry: dict[str, Any], prefix: str, errors: list[str]) -> None:
    """Validate the 'phase' field."""
    phase = entry.get("phase")
    if not isinstance(phase, int) or phase < 1:
        errors.append(f"{prefix}: 'phase' must be a positive integer")


def _check_field_status(entry: dict[str, Any], prefix: str, errors: list[str]) -> None:
    """Validate the 'status' field."""
    if entry.get("status") not in _VALID_STATUSES:
        errors.append(
            f"{prefix}: 'status' must be one of {sorted(_VALID_STATUSES)}, got {entry.get('status')!r}"
        )


def _check_field_description(entry: dict[str, Any], prefix: str, errors: list[str]) -> None:
    """Validate the 'description' field."""
    if not isinstance(entry.get("description"), str) or not entry.get("description"):
        errors.append(f"{prefix}: 'description' must be a non-empty string")


def _check_test_node_id_item(node_id: Any, idx: int, prefix: str, errors: list[str]) -> None:
    """Validate a single test_node_ids entry."""
    if not isinstance(node_id, str) or not node_id:
        errors.append(f"{prefix}: 'test_node_ids[{idx}]' must be a non-empty string")


def _check_field_test_node_ids(entry: dict[str, Any], prefix: str, errors: list[str]) -> None:
    """Validate the optional 'test_node_ids' field if present."""
    if "test_node_ids" not in entry:
        return
    node_ids = entry.get("test_node_ids")
    if not isinstance(node_ids, list):
        errors.append(f"{prefix}: 'test_node_ids' must be an array of strings")
        return
    for index, node_id in enumerate(node_ids):
        _check_test_node_id_item(node_id, index, prefix, errors)


def _validate_scalar_fields(entry: dict[str, Any], idx: int, errors: list[str]) -> None:
    """Validate id, target, phase, status, description, test_node_ids fields."""
    prefix = f"analysers[{idx}]"
    _check_field_id(entry, prefix, errors)
    _check_field_target(entry, prefix, errors)
    _check_field_phase(entry, prefix, errors)
    _check_field_status(entry, prefix, errors)
    _check_field_description(entry, prefix, errors)
    _check_field_test_node_ids(entry, prefix, errors)


def _parse_single_analyser(entry: Any, idx: int) -> tuple[AnalyserContract | None, list[str]]:
    """Parse a single [[analysers]] entry."""
    errors: list[str] = []
    prefix = f"analysers[{idx}]"

    if not isinstance(entry, dict):
        return None, [f"{prefix}: expected a table, got {type(entry).__name__}"]

    errors.extend(_validate_required_keys(entry, idx))
    _validate_scalar_fields(entry, idx, errors)

    states_raw = entry.get("states", {})
    if not isinstance(states_raw, dict):
        errors.append(f"{prefix}: 'states' must be a table")
        return None, errors

    states, state_errors = _parse_states(states_raw, f"{prefix}.states")
    errors.extend(state_errors)

    if errors:
        return None, errors

    contract = AnalyserContract(
        id=str(entry["id"]),
        target=str(entry["target"]),
        phase=int(entry["phase"]),
        status=str(entry["status"]),
        description=str(entry["description"]),
        states=states,
        test_node_ids=_coerce_test_node_ids(entry.get("test_node_ids")),
    )
    return contract, errors


def _coerce_test_node_ids(node_ids: Any) -> tuple[str, ...]:
    """Coerce the raw test_node_ids value into a tuple of strings."""
    if not isinstance(node_ids, list):
        return ()
    return tuple(str(node_id) for node_id in node_ids)


def _check_exit_bounds_present(exit_min: Any, exit_max: Any, full_prefix: str) -> str | None:
    """Return error if exit_min or exit_max is missing."""
    if exit_min is None or exit_max is None:
        return f"{full_prefix}: missing exit_min or exit_max"
    return None


def _check_state_exit_range(
    state_name: str, state_data: dict[str, Any], full_prefix: str
) -> tuple[int, int, str | None]:
    """Validate exit_min/exit_max; return (min, max, error_or_none)."""
    del state_name  # reserved for future use
    exit_min = state_data.get("exit_min")
    exit_max = state_data.get("exit_max")

    err = _check_exit_bounds_present(exit_min, exit_max, full_prefix)
    if err is not None:
        return 0, 0, err

    if not isinstance(exit_min, int):
        return 0, 0, f"{full_prefix}: exit_min must be an integer"
    if not isinstance(exit_max, int):
        return 0, 0, f"{full_prefix}: exit_max must be an integer"
    if exit_min > exit_max:
        return 0, 0, f"{full_prefix}: exit_min ({exit_min}) > exit_max ({exit_max})"
    return exit_min, exit_max, None


def _check_state_signal(
    state_data: dict[str, Any], full_prefix: str
) -> tuple[str | None, str | None]:
    """Validate the optional 'signal' field; return (signal_value, error_message)."""
    signal = state_data.get("signal")
    if signal is not None and not isinstance(signal, str):
        return None, f"{full_prefix}: signal must be a string"
    return signal, None


def _validate_single_state(
    state_name: str, state_data: Any, prefix: str
) -> tuple[StateContract | None, list[str]]:
    """Validate a single state entry and return the parsed contract."""
    full_prefix = f"{prefix}.{state_name}"

    if not isinstance(state_data, dict):
        return None, [f"{full_prefix}: expected a table"]

    unknown_keys = set(state_data.keys()) - _VALID_STATE_KEYS
    if unknown_keys:
        return None, [f"{full_prefix}: unknown keys: {', '.join(sorted(unknown_keys))}"]

    exit_min, exit_max, range_err = _check_state_exit_range(state_name, state_data, full_prefix)
    if range_err is not None:
        return None, [range_err]

    signal, signal_err = _check_state_signal(state_data, full_prefix)
    if signal_err is not None:
        return None, [signal_err]

    sc = StateContract(name=state_name, exit_min=exit_min, exit_max=exit_max, signal=signal)
    return sc, []


def _parse_states(raw: dict[str, Any], prefix: str) -> tuple[dict[str, StateContract], list[str]]:
    """Parse the [analysers.states] table."""
    errors: list[str] = []
    states: dict[str, StateContract] = {}

    for state_name, state_data in raw.items():
        sc, sc_errors = _validate_single_state(state_name, state_data, prefix)
        if sc is not None:
            states[state_name] = sc
        errors.extend(sc_errors)

    return states, errors


def _check_duplicate_ids(contracts: list[AnalyserContract], errors: list[str]) -> None:
    """Check for duplicate analyser IDs."""
    seen: dict[str, int] = {}
    for c in contracts:
        seen[c.id] = seen.get(c.id, 0) + 1
    for aid, count in seen.items():
        if count > 1:
            errors.append(f"Duplicate analyser ID '{aid}' appears {count} times")


# ---------------------------------------------------------------------------
# Contract validation
# ---------------------------------------------------------------------------


def _check_required_states(contract: AnalyserContract) -> list[str]:
    """Check that the contract has all required states defined."""
    missing = [s for s in _REQUIRED_STATES if s not in contract.states]
    if missing:
        return [f"analyser '{contract.id}' is missing required state(s): {', '.join(missing)}"]
    return []


def _has_signal(state: StateContract) -> bool:
    """Return True if the state contract has a signal defined."""
    return state.signal is not None


def _exit_ranges_overlap(a: StateContract, b: StateContract) -> bool:
    """Return True if the exit-code ranges of *a* and *b* overlap."""
    return a.exit_max >= b.exit_min and b.exit_max >= a.exit_min


def _check_overlapping_states(contract: AnalyserContract) -> list[str]:
    """Check for overlapping exit-code ranges between states."""
    names = sorted(contract.states.keys())
    for index, state_name in enumerate(names):
        for compared_name in names[index + 1 :]:
            state = contract.states[state_name]
            compared_state = contract.states[compared_name]
            if _has_signal(state) or _has_signal(compared_state):
                continue
            if _exit_ranges_overlap(state, compared_state):
                overlap = (
                    f"analyser '{contract.id}': state '{state.name}' "
                    f"({state.exit_min}-{state.exit_max}) overlaps "
                    f"'{compared_state.name}' "
                    f"({compared_state.exit_min}-{compared_state.exit_max})"
                )
                return [overlap]
    return []


def validate_contracts(contracts: list[AnalyserContract]) -> list[str]:
    """Validate contracts beyond schema: required states, sensible phase mapping."""
    errors: list[str] = []
    for c in contracts:
        errors.extend(_check_required_states(c))
        errors.extend(_check_overlapping_states(c))
    return errors


def collect_coverage_gap_warnings(contracts: list[AnalyserContract]) -> list[str]:
    """Return informational warnings for active analysers without test coverage.

    A warning (not an error) is emitted for every active analyser that
    declares no ``test_node_ids`` so coverage gaps remain visible without
    failing the gate.

    Args:
        contracts: Parsed analyser contracts to inspect.

    Returns:
        A list of human-readable warning strings.
    """
    warnings: list[str] = []
    for c in contracts:
        if c.status == "active" and not c.test_node_ids:
            warnings.append(f"active analyser '{c.id}' declares no test_node_ids (coverage gap)")
    return warnings


# ---------------------------------------------------------------------------
# Analyser execution
# ---------------------------------------------------------------------------


def _describe_states(states: dict[str, StateContract]) -> str:
    """Return a human-readable summary of declared states."""
    parts = [f"{s.name}({s.exit_min}-{s.exit_max})" for s in states.values()]
    return ", ".join(parts)


def run_analyser(
    analyser: AnalyserContract,
    cwd: Path,
    timeout_s: int = 300,
) -> ContractResult:
    """Run a single analyser and check its exit code against the contract."""
    start = time.monotonic()
    cmd = ["make", analyser.target]
    signal_name: str | None = None
    exit_code: int = -1
    stdout_tail = ""
    stderr_tail = ""

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout_s,
            check=False,
        )
        exit_code = proc.returncode
        signal_name = None
        stdout_tail = _tail(proc.stdout, 300)
        stderr_tail = _tail(proc.stderr, 300)
    except subprocess.TimeoutExpired:
        exit_code = -1
        signal_name = "SIGTERM"
        stderr_tail = "TIMEOUT"
    except OSError as exc:
        exit_code = -1
        stderr_tail = f"Could not execute: {exc}"

    elapsed = time.monotonic() - start
    matched = _match_state(analyser, exit_code, signal_name)
    declared = _describe_states(analyser.states)

    return ContractResult(
        analyser_id=analyser.id,
        target=analyser.target,
        exit_code=exit_code,
        signal_name=signal_name,
        matched_state=matched,
        duration_s=elapsed,
        expected=matched is not None,
        stdout_snippet=stdout_tail,
        stderr_snippet=stderr_tail,
        declared_states=declared,
    )


def _tail(text: str, max_chars: int) -> str:
    """Return the last *max_chars* characters of *text*."""
    if len(text) <= max_chars:
        return text
    return "…" + text[-max_chars:]


def _match_state(analyser: AnalyserContract, exit_code: int, signal_name: str | None) -> str | None:
    """Return the state name if *exit_code* and *signal_name* match, else None."""
    for state in analyser.states.values():
        if state.matches(exit_code, signal_name):
            return state.name
    return None


# ---------------------------------------------------------------------------
# Selection logic
# ---------------------------------------------------------------------------


class PendingPolicy(Enum):
    """Controls whether pending analyser contracts are selected."""

    SKIP = "skip"
    INCLUDE = "include"


@dataclass(frozen=True, slots=True)
class SelectionOptions:
    """Immutable analyser-selection criteria."""

    only: str | None
    pending_policy: PendingPolicy


# owner: quality-infrastructure; reason: backwards-compatible private pending selection API
def _should_skip_pending(  # nosemgrep: boolean-flag-argument
    contract: AnalyserContract, pending_ok: bool
) -> bool:
    """Return True if *contract* should be skipped as a pending analyser."""
    policy = PendingPolicy.INCLUDE if pending_ok else PendingPolicy.SKIP
    return _should_skip_pending_with_policy(contract, policy)


def _should_skip_pending_with_policy(contract: AnalyserContract, policy: PendingPolicy) -> bool:
    """Return whether a contract should be skipped under an explicit policy."""
    return contract.status == "pending" and policy is PendingPolicy.SKIP


def _matches_only_filter(contract: AnalyserContract, only: str | None) -> bool:
    """Return True if *contract* passes the --only filter (or no filter)."""
    if only is None:
        return True
    return only in contract.id or only in contract.target


# owner: quality-infrastructure; reason: backwards-compatible positional analyser selection API
def _select_contracts(  # nosemgrep: boolean-flag-argument
    contracts: list[AnalyserContract],
    only: str | None,
    pending_ok: bool,
) -> tuple[list[AnalyserContract], list[str]]:
    """Select contracts using the established boolean compatibility API.

    Returns:
        A tuple of (selected_contracts, skipped_pending_ids).
    """
    pending_policy = PendingPolicy.INCLUDE if pending_ok else PendingPolicy.SKIP
    options = SelectionOptions(only=only, pending_policy=pending_policy)
    return _select_contracts_with_policy(contracts, options)


def _select_contracts_with_policy(
    contracts: list[AnalyserContract], options: SelectionOptions
) -> tuple[list[AnalyserContract], list[str]]:
    """Select contracts using an explicit pending policy."""
    selected: list[AnalyserContract] = []
    skipped: list[str] = []
    for c in contracts:
        if _should_skip_pending_with_policy(c, options.pending_policy):
            skipped.append(c.id)
        elif _matches_only_filter(c, options.only):
            selected.append(c)
    return selected, skipped


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _format_schema_errors(errors: list[str]) -> str:
    """Format schema errors as text."""
    lines = ["  SCHEMA ERRORS:"]
    for err in errors:
        lines.append(f"    {err}")
    return "\n".join(lines)


def _format_warnings(warnings: list[str]) -> list[str]:
    """Format informational warnings as text lines."""
    if not warnings:
        return []
    lines = [f"  WARNINGS ({len(warnings)}):"]
    for w in warnings:
        lines.append(f"    - {w}")
    return lines


def _format_summary(result_count: int, passed: int, failed: int, skipped: list[str]) -> list[str]:
    """Format the summary section."""
    lines = [
        f"\n  Analysers evaluated: {result_count}",
        f"  Passed: {passed}, Failed: {failed}",
    ]
    if skipped:
        lines.append(f"  Skipped (pending): {len(skipped)}")
        for aid in skipped:
            lines.append(f"    - {aid}")
    return lines


def _append_failure_details(r: ContractResult, lines: list[str]) -> None:
    """Append declared states and stderr info for a failed result."""
    if r.declared_states:
        lines.append(f"         declared: {r.declared_states}")
    if r.stderr_snippet.strip():
        lines.append(f"         stderr: {r.stderr_snippet.strip()[:200]}")


def _format_result_line(r: ContractResult) -> list[str]:
    """Format a single result as text lines."""
    status = "PASS" if r.passed else "FAIL"
    matched = r.matched_state or "unknown"
    sig = f" signal={r.signal_name}" if r.signal_name else ""
    result_line = "".join(
        (
            f"  [{status}] {r.analyser_id:<30} exit={r.exit_code:>3}{sig:<14} ",
            f"→ {matched:<18} ({r.duration_s:.1f}s)",
        )
    )
    lines = [result_line]
    if not r.passed:
        _append_failure_details(r, lines)
    return lines


def _count_passed(results: list[ContractResult]) -> int:
    """Count the number of passed results."""
    total = 0
    for r in results:
        if r.passed:
            total += 1
    return total


def _count_failed(results: list[ContractResult]) -> int:
    """Count the number of failed results."""
    return len(results) - _count_passed(results)


def _format_report(report: RunReport, contracts_path: Path) -> str:
    """Format the run report as human-readable text."""
    lines: list[str] = []
    lines.append(f"Analyser Contract Check — {contracts_path}")
    lines.append("=" * 72)

    if report.schema_errors:
        return lines[0] + "\n" + lines[1] + "\n" + _format_schema_errors(report.schema_errors)

    passed = _count_passed(report.results)
    failed = _count_failed(report.results)
    lines.extend(_format_summary(len(report.results), passed, failed, report.skipped_pending))

    if not report.results:
        if not report.skipped_pending:
            lines.append("  No analysers to run.")
        lines.extend(_format_warnings(report.warnings))
        return "\n".join(lines)

    lines.append("")
    lines.append("-" * 72)

    for result in report.results:
        lines.extend(_format_result_line(result))

    lines.append("-" * 72)
    lines.append(f"  Final: {passed} passed, {failed} failed")
    lines.extend(_format_warnings(report.warnings))
    return "\n".join(lines)


def _format_json(report: RunReport, contracts_path: Path) -> str:
    """Format the run report as JSON."""
    passed = _count_passed(report.results)
    failed = _count_failed(report.results)
    payload: dict[str, Any] = {
        "contracts_path": str(contracts_path),
        "schema_valid": not report.schema_errors,
        "schema_errors": report.schema_errors,
        "warnings": report.warnings,
        "analyser_count": len(report.results),
        "passed": passed,
        "failed": failed,
        "skipped_pending": report.skipped_pending,
        "results": [
            {
                "analyser_id": r.analyser_id,
                "target": r.target,
                "exit_code": r.exit_code,
                "signal": r.signal_name,
                "matched_state": r.matched_state,
                "expected": r.expected,
                "duration_s": round(r.duration_s, 1),
                "declared_states": r.declared_states,
                "stderr_snippet": r.stderr_snippet.strip()[:500],
            }
            for r in report.results
        ],
    }
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_report(
    contracts: list[AnalyserContract],
    args: argparse.Namespace,
) -> RunReport:
    """Build a RunReport from loaded contracts and CLI args."""
    pending_policy = PendingPolicy.INCLUDE if args.pending_ok else PendingPolicy.SKIP
    options = SelectionOptions(only=args.only, pending_policy=pending_policy)
    selected, skipped = _select_contracts_with_policy(contracts, options)
    report = RunReport(skipped_pending=skipped)

    for c in selected:
        result = run_analyser(c, _PROJECT_ROOT, timeout_s=args.timeout)
        report.results.append(result)

    return report


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check analyser behaviour against declared contracts.",
    )
    parser.add_argument(
        "--contracts",
        type=Path,
        default=_DEFAULT_CONTRACTS,
        help=f"Path to analyser-contracts.toml (default: {_DEFAULT_CONTRACTS})",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Only validate the TOML schema; do not run analysers.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run non-pending analysers and verify exit codes.",
    )
    parser.add_argument(
        "--pending-ok",
        action="store_true",
        help="Treat pending analysers as acceptable (run them if selected).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in machine-readable JSON.",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Run only analysers whose ID or target contains this substring.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout per analyser in seconds (default: 300).",
    )
    return parser.parse_args(argv)


def _should_validate(args: argparse.Namespace) -> bool:
    """Return True if schema validation should be performed."""
    return args.validate or not args.run


def _should_run(args: argparse.Namespace) -> bool:
    """Return True if analysers should be executed."""
    return args.run or not args.validate


def _exit_on_result(report: RunReport) -> None:
    """Exit with the appropriate code based on the report."""
    if report.all_contracts_honoured:
        sys.exit(_EXIT_ALL_PASS)
    sys.exit(_EXIT_CONTRACT_BREACH)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    contracts, schema_errors = load_contracts(args.contracts)

    if _should_validate(args):
        schema_errors.extend(validate_contracts(contracts))

    if schema_errors:
        _output_and_exit(RunReport(schema_errors=schema_errors), args)
        sys.exit(_EXIT_SCHEMA_FAIL)

    warnings = collect_coverage_gap_warnings(contracts)

    if not _should_run(args):
        _output_and_exit(RunReport(warnings=warnings), args)
        sys.exit(_EXIT_ALL_PASS)

    report = _build_report(contracts, args)
    report.warnings.extend(warnings)
    _output_and_exit(report, args)
    _exit_on_result(report)


def _output_and_exit(report: RunReport, args: argparse.Namespace) -> None:
    """Print the report in the requested format."""
    if args.json:
        print(_format_json(report, args.contracts))
    else:
        print(_format_report(report, args.contracts))


if __name__ == "__main__":
    main()
