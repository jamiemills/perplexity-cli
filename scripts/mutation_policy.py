"""Canonical, fail-closed classification for Mutmut 3.5 evidence."""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess  # nosec B404  # owner: quality-infrastructure; reason: only the fixed pinned mutmut command is executed without a shell
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.mutation_evidence import (  # noqa: E402  # owner: quality-infrastructure; reason: package import follows the direct-script repository-root bootstrap
    EvidenceDisagreements,
    EvidenceSummary,
    MutationSelection,
    compare_evidence,
    digest_records,
    matches_selection,
)

logger = logging.getLogger(__name__)

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_TOOL_ERROR = 2

TOOL_NAME = "mutmut"
LOCKED_MUTMUT_VERSION = "3.5.0"
LOCKED_WHEEL_FILENAME = "mutmut-3.5.0-py3-none-any.whl"
LOCKED_WHEEL_SHA256 = "f19f2dd2e977eb9dc17255d8cb11e24fbfc3191620fba3108cac25779c9d78c9"
UNKNOWN_VALUE = "unknown"
STATUS_CLEAN = "clean"
STATUS_FINDINGS = "findings"
STATUS_TOOL_ERROR = "tool-error"
STATUS_NOT_APPLICABLE = "not-applicable"

type AggregateStatus = Literal["clean", "findings", "tool-error", "not-applicable"]
type RunOutcome = Literal["completed", "interrupted", "timed-out", "failed", "not-applicable"]
type ReportInvariant = Callable[[], bool]

ACTIONABLE_CATEGORIES = frozenset({"survived", "timeout", "suspicious", "no_tests"})
UNSAFE_CATEGORIES = frozenset({"skipped", "not_checked", "interrupted", "segfault", "unknown"})
CATEGORY_ORDER = (
    "killed",
    "survived",
    "timeout",
    "suspicious",
    "no_tests",
    "skipped",
    "not_checked",
    "interrupted",
    "segfault",
    "caught_by_type_check",
    "unknown",
)
STATUS_TO_CATEGORY = {
    "killed": "killed",
    "survived": "survived",
    "timeout": "timeout",
    "suspicious": "suspicious",
    "no tests": "no_tests",
    "skipped": "skipped",
    "not checked": "not_checked",
    "check was interrupted by user": "interrupted",
    "segfault": "segfault",
    "caught by type check": "caught_by_type_check",
}

_MUTMUT_PREFIX = ("uv", "run", "mutmut")
_MUTMUT_TIMEOUT_S = 120
_LINE_PATTERN = re.compile(r"^    (?P<key>.+): (?P<status>.+)$")
_VERSION_PATTERN = re.compile(r"^mutmut, version (?P<version>\S+)\s*$")
_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_NO_DISAGREEMENTS = EvidenceDisagreements()


class ResultsParseError(ValueError):
    """Raised when a Mutmut result line is malformed."""


class MutmutUnavailableError(RuntimeError):
    """Raised when the pinned Mutmut command cannot provide evidence."""


class ReportValidationError(ValueError):
    """Raised when a report violates canonical semantic invariants."""


@dataclass(frozen=True, slots=True)
class MutantEntry:
    """One raw Mutmut result and its normalised category."""

    key: str
    status: str
    category: str


@dataclass(frozen=True, slots=True)
class CategoryCounts:
    """Counts for every distinct Mutmut 3.5 result category."""

    killed: int = 0
    survived: int = 0
    timeout: int = 0
    suspicious: int = 0
    no_tests: int = 0
    skipped: int = 0
    not_checked: int = 0
    interrupted: int = 0
    segfault: int = 0
    caught_by_type_check: int = 0
    unknown: int = 0


@dataclass(frozen=True, slots=True)
class Provenance:
    """Immutable source and tracked-input identity for a mutation run."""

    source_revision: str
    source_tree: str
    input_fingerprint: str
    evidence_current: bool


@dataclass(frozen=True, slots=True)
class EnvironmentIdentity:
    """Path-independent execution environment identity supplied by T003."""

    python_implementation: str
    python_version: str
    python_cache_tag: str
    platform: str
    uv_version: str
    installed_distributions_digest: str
    mutmut_distribution_digest: str
    mutmut_record_digest: str
    locked_wheel_filename: str
    locked_wheel_sha256: str


@dataclass(frozen=True, slots=True)
class ReportContext:
    """Declared context shared by successful and failed reports."""

    version: str
    selection: MutationSelection
    provenance: Provenance
    environment: EnvironmentIdentity
    run_outcome: RunOutcome


@dataclass(frozen=True, slots=True)
class PolicyInput:
    """Complete pure input to canonical mutation classification."""

    context: ReportContext
    generated_keys: tuple[str, ...]
    disagreements: EvidenceDisagreements
    results_text: str


@dataclass(frozen=True, slots=True)
class ReportEvidence:
    """Serialisable evidence counts, differences and digests."""

    generated_count: int
    selected_count: int
    result_count: int
    checked_count: int
    missing_results: tuple[str, ...]
    extra_results: tuple[str, ...]
    duplicate_generated: tuple[str, ...]
    duplicate_results: tuple[str, ...]
    dictionary_disagreements: tuple[str, ...]
    structural_exclusion_disagreements: tuple[str, ...]
    complete: bool
    generated_digest: str
    result_digest: str


@dataclass(frozen=True, slots=True)
class MutationReport:
    """Canonical mutation report consumed by local and CI policy lanes."""

    context: ReportContext
    evidence: ReportEvidence
    categories: CategoryCounts
    status: AggregateStatus
    findings: tuple[MutantEntry, ...]
    unsafe_results: tuple[MutantEntry, ...]
    error: str = ""


def parse_results_text(text: str) -> list[MutantEntry]:
    """Parse exact ``mutmut results --all`` lines without dropping unknowns.

    Args:
        text: Raw stdout from Mutmut 3.5.

    Returns:
        Parsed entries. Unknown raw statuses have category ``unknown`` so a
        tool-error report can retain them.

    Raises:
        ResultsParseError: If any non-blank line has malformed structure.
    """
    return [_parse_entry_line(line) for line in text.splitlines() if line.strip()]


def parse_version_text(text: str) -> str:
    """Parse the exact Mutmut version banner without reflecting its content.

    Args:
        text: Captured version command output.

    Returns:
        Parsed version string.

    Raises:
        MutmutUnavailableError: If the banner does not match Mutmut's contract.
    """
    match = _VERSION_PATTERN.match(text)
    if match is None:
        msg = "unparseable mutmut version output"
        raise MutmutUnavailableError(msg)
    return match.group("version")


def build_report(
    context: ReportContext,
    generated_keys: tuple[str, ...],
    entries: list[MutantEntry],
    disagreements: EvidenceDisagreements = _NO_DISAGREEMENTS,
) -> MutationReport:
    """Build a canonical report from independent generated and raw evidence.

    Args:
        context: Authoritative run context.
        generated_keys: Independently enumerated generated mutant keys.
        entries: Parsed Mutmut result records.
        disagreements: Independent dictionary and exclusion failures.

    Returns:
        Classified mutation report.
    """
    selected_entries = _selected_entries(entries, context.selection)
    summary = compare_evidence(
        generated_keys,
        (entry.key for entry in entries),
        context.selection,
        disagreements,
    )
    categories = _count_categories(selected_entries)
    evidence = _report_evidence(summary, selected_entries, categories.not_checked)
    status, error = _classify_report(context, evidence, categories)
    findings = _unique_entries(_entries_in_categories(selected_entries, ACTIONABLE_CATEGORIES))
    unsafe_results = _unique_entries(_entries_in_categories(selected_entries, UNSAFE_CATEGORIES))
    return MutationReport(context, evidence, categories, status, findings, unsafe_results, error)


def build_tool_error_report(
    context: ReportContext,
    message: str,
    generated_keys: tuple[str, ...] = (),
    disagreements: EvidenceDisagreements = _NO_DISAGREEMENTS,
) -> MutationReport:
    """Build a provenance-preserving tool-error report.

    Args:
        context: Best available run context.
        message: Safe error summary without captured process output.
        generated_keys: Any independently enumerated generated keys.
        disagreements: Independent dictionary and exclusion failures.

    Returns:
        Canonical tool-error report.
    """
    summary = compare_evidence(
        generated_keys,
        (),
        context.selection,
        disagreements,
    )
    evidence = _report_evidence(summary, (), 0)
    return MutationReport(
        context=context,
        evidence=evidence,
        categories=CategoryCounts(),
        status=STATUS_TOOL_ERROR,
        findings=(),
        unsafe_results=(),
        error=message,
    )


def report_to_dict(report: MutationReport) -> dict[str, Any]:
    """Serialise and semantically validate a canonical report.

    Args:
        report: Report to serialise.

    Returns:
        Validated JSON-compatible payload.
    """
    context = report.context
    payload: dict[str, Any] = {
        "schema_version": 2,
        "tool": TOOL_NAME,
        "version": context.version,
        "scope": {
            "kind": context.selection.scope,
            "patterns": list(context.selection.patterns),
        },
        "provenance": _provenance_to_dict(context.provenance),
        "environment": _environment_to_dict(context.environment),
        "run_outcome": context.run_outcome,
        "total_mutants": report.evidence.result_count,
        "evidence": _evidence_to_dict(report.evidence),
        "categories": _counts_to_dict(report.categories),
        "status": report.status,
        "findings": [_entry_to_dict(entry) for entry in report.findings],
        "unsafe_results": [_entry_to_dict(entry) for entry in report.unsafe_results],
    }
    if report.error:
        payload["error"] = report.error
    validate_report_payload(payload)
    return payload


def validate_report_payload(payload: dict[str, Any]) -> None:
    """Reject a mutation payload whose semantic records do not reconcile.

    Args:
        payload: Canonical report payload before writing or publication.

    Raises:
        ReportValidationError: If any arithmetic, identity or record invariant
            is violated.
    """
    evidence = payload["evidence"]
    categories = payload["categories"]
    _require(lambda: payload["total_mutants"] == evidence["result_count"], "total/result mismatch")
    _require(
        lambda: sum(categories.values()) == evidence["result_count"], "category/result mismatch"
    )
    expected_checked = evidence["result_count"] - categories["not_checked"]
    _require(lambda: evidence["checked_count"] == expected_checked, "checked count mismatch")
    _require(
        lambda: evidence["selected_count"] <= evidence["generated_count"],
        "selected exceeds generated",
    )
    if payload["status"] == STATUS_TOOL_ERROR:
        _validate_detail_records(payload["findings"], categories, ACTIONABLE_CATEGORIES, "findings")
        _validate_detail_records(
            payload["unsafe_results"], categories, UNSAFE_CATEGORIES, "unsafe results"
        )
    else:
        _validate_record_set(payload["findings"], categories, ACTIONABLE_CATEGORIES, "findings")
        _validate_record_set(
            payload["unsafe_results"], categories, UNSAFE_CATEGORIES, "unsafe results"
        )
    _validate_evidence_lists(evidence)
    _validate_completeness(payload)
    _validate_status_semantics(payload, categories)
    _validate_publishable_identity(payload)


def _validate_evidence_lists(evidence: dict[str, Any]) -> None:
    fields = (
        "missing_results",
        "extra_results",
        "duplicate_generated",
        "duplicate_results",
        "dictionary_disagreements",
        "structural_exclusion_disagreements",
    )
    for field in fields:
        values = evidence[field]
        _require(
            lambda values=values: len(values) == len(set(values)),
            f"duplicate {field} entry",
        )


def _validate_completeness(payload: dict[str, Any]) -> None:
    evidence = payload["evidence"]
    issue_fields = (
        "missing_results",
        "extra_results",
        "duplicate_generated",
        "duplicate_results",
        "dictionary_disagreements",
        "structural_exclusion_disagreements",
    )
    expected = (
        evidence["selected_count"] > 0
        and evidence["selected_count"] == evidence["result_count"]
        and not any(evidence[field] for field in issue_fields)
    )
    _require(lambda: evidence["complete"] is expected, "invalid or incomplete completeness flag")
    if payload["scope"]["kind"] == "full":
        _require(
            lambda: evidence["selected_count"] == evidence["generated_count"],
            "full-scope count mismatch",
        )


def _validate_status_semantics(payload: dict[str, Any], categories: dict[str, int]) -> None:
    status = payload["status"]
    if status == STATUS_TOOL_ERROR:
        return
    if status == STATUS_NOT_APPLICABLE:
        _validate_not_applicable_payload(payload)
        return
    _validate_completed_payload(payload, categories)


def _validate_not_applicable_payload(payload: dict[str, Any]) -> None:
    evidence = payload["evidence"]
    _require(lambda: payload["run_outcome"] == "not-applicable", "invalid not-applicable outcome")
    empty = evidence["selected_count"] == 0 and evidence["result_count"] == 0
    _require(lambda: empty, "non-empty not-applicable evidence")


def _validate_completed_payload(payload: dict[str, Any], categories: dict[str, int]) -> None:
    evidence = payload["evidence"]
    actionable = sum(categories[item] for item in ACTIONABLE_CATEGORIES)
    unsafe = sum(categories[item] for item in UNSAFE_CATEGORIES)
    _require(lambda: payload["run_outcome"] == "completed", "publishable run is not completed")
    _require(
        lambda: evidence["complete"] is True and evidence["selected_count"] > 0,
        "publishable evidence is incomplete",
    )
    _require(lambda: unsafe == 0, "publishable evidence is unsafe")
    _require(
        lambda: (payload["status"] == STATUS_FINDINGS) == (actionable > 0),
        "status/actionable mismatch",
    )


def _validate_record_set(
    records: list[dict[str, str]],
    categories: dict[str, int],
    expected_categories: frozenset[str],
    label: str,
) -> None:
    keys = [record["key"] for record in records]
    _require(lambda: len(keys) == len(set(keys)), f"duplicate {label}")
    actual = Counter(record["category"] for record in records)
    expected = Counter({category: categories[category] for category in expected_categories})
    _require(lambda: actual == +expected, f"{label} do not correspond to categories")
    for record in records:
        expected_category = STATUS_TO_CATEGORY.get(record["status"], "unknown")
        _require(
            lambda record=record, expected_category=expected_category: (
                record["category"] == expected_category
            ),
            f"{label} status/category mismatch",
        )


def _validate_detail_records(
    records: list[dict[str, str]],
    categories: dict[str, int],
    expected_categories: frozenset[str],
    label: str,
) -> None:
    keys = [record["key"] for record in records]
    _require(lambda: len(keys) == len(set(keys)), f"duplicate {label}")
    actual = Counter(record["category"] for record in records)
    for category in expected_categories:
        expected_count = categories[category]
        valid_count = _detail_count_corresponds(actual[category], expected_count)
        _require(
            lambda valid_count=valid_count: valid_count, f"{label} do not correspond to categories"
        )
    _validate_detail_statuses(records, expected_categories, label)


def _validate_detail_statuses(
    records: list[dict[str, str]], expected_categories: frozenset[str], label: str
) -> None:
    for record in records:
        expected_category = STATUS_TO_CATEGORY.get(record["status"], "unknown")
        valid = record["category"] == expected_category and expected_category in expected_categories
        _require(lambda valid=valid: valid, f"invalid {label} detail")


def _detail_count_corresponds(actual: int, expected: int) -> bool:
    return actual == 0 if expected == 0 else 1 <= actual <= expected


def _validate_publishable_identity(payload: dict[str, Any]) -> None:
    if payload["status"] == STATUS_TOOL_ERROR:
        return
    provenance = payload["provenance"]
    environment = payload["environment"]
    _require(lambda: payload["version"] == LOCKED_MUTMUT_VERSION, "wrong Mutmut version")
    _require(lambda: provenance["evidence_current"] is True, "stale evidence identity")
    _require(
        lambda: _REVISION_PATTERN.fullmatch(provenance["source_revision"]) is not None,
        "invalid source revision",
    )
    _require(
        lambda: _REVISION_PATTERN.fullmatch(provenance["source_tree"]) is not None,
        "invalid source tree",
    )
    _require(
        lambda: _DIGEST_PATTERN.fullmatch(provenance["input_fingerprint"]) is not None,
        "invalid input fingerprint",
    )
    _validate_environment(environment)


def _validate_environment(environment: dict[str, str]) -> None:
    identity_fields = (
        "python_implementation",
        "python_version",
        "python_cache_tag",
        "platform",
        "uv_version",
    )
    _require(
        lambda: all(not _placeholder(environment[field]) for field in identity_fields),
        "incomplete environment identity",
    )
    digest_fields = (
        "installed_distributions_digest",
        "mutmut_distribution_digest",
        "mutmut_record_digest",
    )
    _require(
        lambda: all(_DIGEST_PATTERN.fullmatch(environment[field]) for field in digest_fields),
        "invalid environment digest",
    )
    _require(
        lambda: environment["locked_wheel_filename"] == LOCKED_WHEEL_FILENAME,
        "wrong locked wheel filename",
    )
    _require(
        lambda: environment["locked_wheel_sha256"] == LOCKED_WHEEL_SHA256,
        "wrong locked wheel digest",
    )


def _placeholder(value: str) -> bool:
    return not value.strip() or value.strip().lower() in {UNKNOWN_VALUE, "tbd", "none", "n/a"}


def _require(invariant: ReportInvariant, message: str) -> None:
    if not invariant():
        raise ReportValidationError(message)


def write_report(report: MutationReport, report_path: Path) -> None:
    """Validate and write a canonical JSON report.

    Args:
        report: Report to validate and write.
        report_path: Destination JSON path.
    """
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_to_dict(report), indent=2) + "\n", encoding="utf-8")
    logger.info("Mutation report written to %s", report_path)


def run_policy(policy_input: PolicyInput, report_path: Path | None = None) -> int:
    """Classify pre-fetched evidence and optionally write its report.

    Args:
        policy_input: Complete pure policy input.
        report_path: Optional report destination.

    Returns:
        Canonical policy exit code.
    """
    try:
        entries = parse_results_text(policy_input.results_text)
    except ResultsParseError:
        logger.warning("Malformed Mutmut result evidence")
        report = build_tool_error_report(
            policy_input.context,
            "malformed mutmut result evidence",
            policy_input.generated_keys,
            policy_input.disagreements,
        )
    else:
        report = build_report(
            policy_input.context,
            policy_input.generated_keys,
            entries,
            policy_input.disagreements,
        )
    if report_path is not None:
        write_report(report, report_path)
    return _exit_code_for_status(report.status)


def detect_version() -> str:
    """Run the pinned Mutmut version command.

    Returns:
        Parsed Mutmut version.
    """
    return parse_version_text(_run_mutmut(("--version",)))


def fetch_results_text() -> str:
    """Run the locked Mutmut 3.5 ``results --all`` command.

    Returns:
        Raw Mutmut result output.
    """
    return _run_mutmut(("results", "--all", "True"))


def placeholder_context(selection: MutationSelection) -> ReportContext:
    """Return an explicitly unknown context for pre-orchestration failures.

    Args:
        selection: Declared mutation selection.

    Returns:
        Context valid only for a tool-error report.
    """
    provenance = Provenance(UNKNOWN_VALUE, UNKNOWN_VALUE, UNKNOWN_VALUE, False)
    environment = EnvironmentIdentity(*([UNKNOWN_VALUE] * 10))
    return ReportContext(UNKNOWN_VALUE, selection, provenance, environment, "failed")


def _parse_entry_line(line: str) -> MutantEntry:
    match = _LINE_PATTERN.match(line)
    if match is None:
        msg = "malformed result line"
        raise ResultsParseError(msg)
    status = match.group("status")
    return MutantEntry(
        key=match.group("key"),
        status=status,
        category=STATUS_TO_CATEGORY.get(status, "unknown"),
    )


def _selected_entries(
    entries: list[MutantEntry], selection: MutationSelection
) -> tuple[MutantEntry, ...]:
    return tuple(entry for entry in entries if matches_selection(entry.key, selection))


def _entries_in_categories(
    entries: tuple[MutantEntry, ...], categories: frozenset[str]
) -> tuple[MutantEntry, ...]:
    return tuple(entry for entry in entries if entry.category in categories)


def _unique_entries(entries: tuple[MutantEntry, ...]) -> tuple[MutantEntry, ...]:
    return tuple(dict.fromkeys(entries))


def _count_categories(entries: tuple[MutantEntry, ...]) -> CategoryCounts:
    tallies: dict[str, int] = dict.fromkeys(CATEGORY_ORDER, 0)
    for entry in entries:
        tallies[entry.category] += 1
    return CategoryCounts(**tallies)


def _report_evidence(
    summary: EvidenceSummary,
    entries: tuple[MutantEntry, ...],
    not_checked_count: int,
) -> ReportEvidence:
    result_records = (f"{entry.key}\0{entry.status}" for entry in entries)
    return ReportEvidence(
        generated_count=summary.generated_count,
        selected_count=summary.selected_count,
        result_count=summary.result_count,
        checked_count=summary.result_count - not_checked_count,
        missing_results=summary.missing_results,
        extra_results=summary.extra_results,
        duplicate_generated=summary.duplicate_generated,
        duplicate_results=summary.duplicate_results,
        dictionary_disagreements=summary.dictionary_disagreements,
        structural_exclusion_disagreements=summary.structural_exclusion_disagreements,
        complete=summary.complete,
        generated_digest=summary.generated_digest,
        result_digest=digest_records(result_records),
    )


def _classify_report(
    context: ReportContext,
    evidence: ReportEvidence,
    categories: CategoryCounts,
) -> tuple[AggregateStatus, str]:
    if context.run_outcome == "not-applicable":
        return _classify_not_applicable(context, evidence, categories)
    error = _tool_error_reason(context, evidence, categories)
    if error:
        return STATUS_TOOL_ERROR, error
    actionable = _category_sum(categories, ACTIONABLE_CATEGORIES)
    return (STATUS_FINDINGS, "") if actionable else (STATUS_CLEAN, "")


def _tool_error_reason(
    context: ReportContext,
    evidence: ReportEvidence,
    categories: CategoryCounts,
) -> str:
    if context.run_outcome != "completed":
        return f"mutation run outcome was {context.run_outcome}"
    identity_error = _context_identity_error(context)
    if identity_error:
        return identity_error
    if _evidence_is_incomplete_or_unsafe(evidence, categories):
        return "mutation evidence is incomplete or unsafe"
    return ""


def _evidence_is_incomplete_or_unsafe(evidence: ReportEvidence, categories: CategoryCounts) -> bool:
    return not evidence.complete or bool(_category_sum(categories, UNSAFE_CATEGORIES))


def _context_identity_error(context: ReportContext) -> str:
    payload = {
        "status": STATUS_CLEAN,
        "version": context.version,
        "provenance": _provenance_to_dict(context.provenance),
        "environment": _environment_to_dict(context.environment),
    }
    try:
        _validate_publishable_identity(payload)
    except ReportValidationError as exc:
        return str(exc)
    return ""


def _classify_not_applicable(
    context: ReportContext, evidence: ReportEvidence, categories: CategoryCounts
) -> tuple[AggregateStatus, str]:
    identity_error = _context_identity_error(context)
    if identity_error:
        return STATUS_TOOL_ERROR, identity_error
    if (
        evidence.selected_count
        or evidence.result_count
        or _category_sum(categories, CATEGORY_ORDER)
    ):
        return STATUS_TOOL_ERROR, "not-applicable evidence must be empty"
    return STATUS_NOT_APPLICABLE, ""


def _category_sum(counts: CategoryCounts, categories: tuple[str, ...] | frozenset[str]) -> int:
    values = _counts_to_dict(counts)
    return sum(values[category] for category in categories)


def _counts_to_dict(counts: CategoryCounts) -> dict[str, int]:
    return {category: getattr(counts, category) for category in CATEGORY_ORDER}


def _entry_to_dict(entry: MutantEntry) -> dict[str, str]:
    return {"key": entry.key, "status": entry.status, "category": entry.category}


def _provenance_to_dict(provenance: Provenance) -> dict[str, str | bool]:
    return {
        "source_revision": provenance.source_revision,
        "source_tree": provenance.source_tree,
        "input_fingerprint": provenance.input_fingerprint,
        "evidence_current": provenance.evidence_current,
    }


def _environment_to_dict(environment: EnvironmentIdentity) -> dict[str, str]:
    return {
        field: getattr(environment, field) for field in EnvironmentIdentity.__dataclass_fields__
    }


def _evidence_to_dict(evidence: ReportEvidence) -> dict[str, int | bool | str | list[str]]:
    return {
        "generated_count": evidence.generated_count,
        "selected_count": evidence.selected_count,
        "result_count": evidence.result_count,
        "checked_count": evidence.checked_count,
        "missing_results": list(evidence.missing_results),
        "extra_results": list(evidence.extra_results),
        "duplicate_generated": list(evidence.duplicate_generated),
        "duplicate_results": list(evidence.duplicate_results),
        "dictionary_disagreements": list(evidence.dictionary_disagreements),
        "structural_exclusion_disagreements": list(evidence.structural_exclusion_disagreements),
        "complete": evidence.complete,
        "generated_digest": evidence.generated_digest,
        "result_digest": evidence.result_digest,
    }


def _exit_code_for_status(status: AggregateStatus) -> int:
    if status in {STATUS_CLEAN, STATUS_NOT_APPLICABLE}:
        return EXIT_CLEAN
    if status == STATUS_FINDINGS:
        return EXIT_FINDINGS
    return EXIT_TOOL_ERROR


def _run_mutmut(args: tuple[str, ...]) -> str:
    command = [*_MUTMUT_PREFIX, *args]
    logger.info("Running: %s", " ".join(command))
    try:
        result = subprocess.run(  # nosec B603  # owner: quality-infrastructure; reason: command arguments are restricted to the pinned mutmut helper contract and shell use is disabled
            command,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            check=False,
            timeout=_MUTMUT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        msg = f"mutmut command timed out after {_MUTMUT_TIMEOUT_S} seconds"
        raise MutmutUnavailableError(msg) from exc
    except (FileNotFoundError, OSError) as exc:
        msg = f"mutmut command unavailable ({type(exc).__name__})"
        raise MutmutUnavailableError(msg) from exc
    if result.returncode != 0:
        msg = f"mutmut exited with status {result.returncode}"
        raise MutmutUnavailableError(msg)
    return result.stdout


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=None)
    parser.add_argument("--scope", choices=("full", "selected"), default="full")
    parser.add_argument("--pattern", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Fetch raw results but fail closed until T003 supplies generated evidence.

    Args:
        argv: Optional command-line arguments.

    Returns:
        Tool-error exit code because this compatibility CLI lacks orchestration.
    """
    args = _parse_args(argv)
    try:
        selection = MutationSelection(args.scope, tuple(args.pattern))
    except ValueError as exc:
        logger.exception("Invalid mutation scope: %s", exc)
        return EXIT_TOOL_ERROR
    context = placeholder_context(selection)
    report = _fetch_cli_report(context)
    if args.report_path is not None:
        write_report(report, args.report_path)
    return EXIT_TOOL_ERROR


def _fetch_cli_report(context: ReportContext) -> MutationReport:
    try:
        version = detect_version()
        results_text = fetch_results_text()
    except MutmutUnavailableError as exc:
        logger.warning("Mutmut unavailable: %s", exc)
        return build_tool_error_report(context, "mutmut unavailable")
    versioned_context = ReportContext(
        version, context.selection, context.provenance, context.environment, "failed"
    )
    if results_text:
        logger.info("Raw Mutmut results retained by the caller")
    return build_tool_error_report(
        versioned_context,
        "independent generated evidence is required",
    )


if __name__ == "__main__":
    sys.exit(main())
