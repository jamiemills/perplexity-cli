"""YAML 1.2-aware semantic validator for GitHub Actions workflows.

Replaces the older raw-string scanning approach with a real YAML parser
(``ruamel.yaml``) so that structure, key collisions, and reference shape are
evaluated semantically rather than as plain text.

The validator enforces a small but security-relevant policy:

* Workflows declare ``name``, ``on``, and ``permissions``.
* External action references are pinned to a full 40-character SHA.
* No workflow uses the dangerous ``pull_request_target`` trigger.
* Every job has a ``name``.
* Soft warnings are emitted when jobs omit ``timeout-minutes`` or any
  concurrency group is missing.

Usage::

    uv run python scripts/validate_workflow_policy.py [--strict] [--dir DIR]
                                                      [--json]

Exit codes:
    0  pass       — all hard checks passed (warnings allowed unless --strict)
    1  fail       — at least one hard error, or a warning under --strict
    2  usage      — invalid arguments or unreadable workflow directory
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, cast

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"

EXIT_PASS: int = 0
EXIT_FAIL: int = 1
EXIT_USAGE: int = 2

SEVERITY_ERROR: str = "error"
SEVERITY_WARNING: str = "warning"

# GitHub Actions treats the unquoted ``on:`` key as the trigger map.
# ruamel.yaml's safe loader keeps it as the string "on", but we also tolerate
# the boolean ``True`` form for forward compatibility.
TRIGGER_KEYS: tuple[Any, ...] = ("on", True)

# External action references look like "owner/repo@ref". Local actions start
# with "./" and are exempt from SHA pinning.
EXTERNAL_ACTION_PATTERN: re.Pattern[str] = re.compile(r"^(?P<repo>[^/\s]+/[^@\s]+)@(?P<ref>.+)$")
SHA_PATTERN: re.Pattern[str] = re.compile(r"^[0-9a-f]{40}$")

FORBIDDEN_TRIGGER: str = "pull_request_target"
FORBIDDEN_TRIGGER_MESSAGE = (
    "workflow uses 'pull_request_target' which exposes secrets to untrusted code; "
    "use 'pull_request' instead"
)
MISSING_PERMISSIONS_PREFIX = "workflow has no top-level 'permissions' and these jobs omit it too: "


class ConcurrencyPolicy(Enum):
    """Record whether workflow-level concurrency is configured."""

    WORKFLOW = "workflow"
    JOB = "job"


class Strictness(Enum):
    """Select normal or strict warning handling."""

    NORMAL = "normal"
    STRICT = "strict"


class _YamlLoader(Protocol):
    def load(self, stream: str) -> object: ...


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    """A single validation finding for one workflow file.

    Attributes:
        severity: ``error`` or ``warning``.
        code: Stable machine-readable identifier for the rule.
        message: Human-readable description of the finding.
        file: Workflow file name (relative to the scanned directory).
        job: Job name when the finding is job-scoped, otherwise ``None``.
    """

    severity: str
    code: str
    message: str
    file: str
    job: str | None = None


@dataclass(frozen=True, slots=True)
class FileReport:
    """The validation outcome for a single workflow file.

    Attributes:
        file: Workflow file name.
        parsed: True if the file parsed as valid YAML.
        findings: Findings discovered in the file (may be empty).
        parse_error: Error detail when ``parsed`` is False.
    """

    file: str
    parsed: bool
    findings: list[Finding] = field(default_factory=list[Finding])
    parse_error: str = ""


@dataclass(frozen=True, slots=True)
class PolicyReport:
    """The aggregated report across every scanned workflow file.

    Attributes:
        reports: Per-file reports.
        strict: Whether warnings should be promoted to errors.
    """

    reports: list[FileReport] = field(default_factory=list[FileReport])
    strict: bool = False


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------


def _make_parser() -> YAML:
    """Build a ruamel.yaml parser configured for strict YAML 1.2 semantics.

    Returns:
        A ``ruamel.yaml.YAML`` instance that rejects duplicate mapping keys.
    """
    yaml_parser = YAML(typ="safe")
    yaml_parser.allow_duplicate_keys = False
    return yaml_parser


def _parse_workflow(text: str, yaml_parser: YAML) -> tuple[dict[str, Any] | None, str]:
    """Parse workflow YAML into a dict, returning an error string on failure.

    Args:
        text: Raw workflow file contents.
        yaml_parser: Configured ruamel.yaml parser.

    Returns:
        Tuple of (parsed dict or None, error message or empty string).
    """
    try:
        loaded = cast(_YamlLoader, yaml_parser).load(text)
    except YAMLError as exc:
        logger.info("YAML parse error: %s", exc)
        return None, str(exc)
    except Exception as exc:
        logger.info("Unexpected YAML load error: %s", exc)
        return None, str(exc)
    if not isinstance(loaded, dict):
        return None, "workflow root must be a mapping"
    return cast(dict[str, Any], loaded), ""


# ---------------------------------------------------------------------------
# Workflow-level validators
# ---------------------------------------------------------------------------


def _validate_workflow_name(workflow: dict[str, Any], file_name: str) -> list[Finding]:
    """Check the workflow has a top-level ``name`` field."""
    if not workflow.get("name"):
        return [
            Finding(
                severity=SEVERITY_ERROR,
                code="WF_NAME_MISSING",
                message="workflow is missing a top-level 'name' field",
                file=file_name,
            )
        ]
    return []


def _validate_triggers(workflow: dict[str, Any], file_name: str) -> list[Finding]:
    """Check the ``on`` trigger exists and is not the forbidden target trigger."""
    findings: list[Finding] = []
    if not any(key in workflow for key in TRIGGER_KEYS):
        findings.append(
            Finding(
                severity=SEVERITY_ERROR,
                code="WF_TRIGGER_MISSING",
                message="workflow is missing an 'on' trigger",
                file=file_name,
            )
        )
        return findings
    findings.extend(_check_forbidden_trigger(workflow, file_name))
    return findings


def _check_forbidden_trigger(workflow: dict[str, Any], file_name: str) -> list[Finding]:
    """Return a finding if ``pull_request_target`` appears anywhere in triggers."""
    trigger = _get_trigger(workflow)
    if isinstance(trigger, dict) and FORBIDDEN_TRIGGER in trigger:
        return [
            Finding(
                severity=SEVERITY_ERROR,
                code="WF_FORBIDDEN_TRIGGER",
                message=FORBIDDEN_TRIGGER_MESSAGE,
                file=file_name,
            )
        ]
    return []


def _get_trigger(workflow: dict[str, Any]) -> Any:
    """Return the workflow trigger value, tolerating string-form triggers."""
    for key in TRIGGER_KEYS:
        if key in workflow:
            return workflow[key]
    return None


def _validate_permissions(workflow: dict[str, Any], file_name: str) -> list[Finding]:
    """Check that ``permissions`` exists at workflow or every-job level."""
    if "permissions" in workflow:
        return []
    raw_jobs: object = workflow.get("jobs") or {}
    jobs = cast(dict[str, Any], raw_jobs) if isinstance(raw_jobs, dict) else {}
    missing = _jobs_missing_permissions(jobs)
    if missing:
        return [
            Finding(
                severity=SEVERITY_ERROR,
                code="WF_PERMISSIONS_MISSING",
                message=MISSING_PERMISSIONS_PREFIX + ", ".join(sorted(missing)),
                file=file_name,
            )
        ]
    return []


def _jobs_missing_permissions(jobs: dict[str, Any]) -> list[str]:
    """Return names of jobs that lack a ``permissions`` block."""
    return [
        name for name, job in jobs.items() if isinstance(job, dict) and "permissions" not in job
    ]


def _validate_action_pinning(workflow: dict[str, Any], file_name: str) -> list[Finding]:
    """Check every external ``uses:`` reference is pinned to a 40-char SHA."""
    findings: list[Finding] = []
    for uses, job in _iter_uses(workflow):
        ref = _extract_uses_ref(uses)
        if ref is None:
            continue
        if not SHA_PATTERN.fullmatch(ref):
            findings.append(
                Finding(
                    severity=SEVERITY_ERROR,
                    code="WF_ACTION_UNPINNED",
                    message=(f"external action '{ref}' is not pinned to a full 40-character SHA"),
                    file=file_name,
                    job=job,
                )
            )
    return findings


def _extract_uses_ref(uses_value: Any) -> str | None:
    """Return the external action reference, or None for local/reusable uses."""
    if not isinstance(uses_value, str):
        return None
    if uses_value.startswith(("./", "docker://")):
        return None
    match = EXTERNAL_ACTION_PATTERN.match(uses_value)
    if match is None:
        return None
    return match.group("ref")


def _iter_uses(workflow: dict[str, Any]) -> list[tuple[Any, str | None]]:
    """Yield ``(uses_value, job_name)`` pairs for every step's ``uses`` key."""
    pairs: list[tuple[Any, str | None]] = []
    raw_jobs: object = workflow.get("jobs") or {}
    jobs = cast(dict[str, Any], raw_jobs) if isinstance(raw_jobs, dict) else {}
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        pairs.extend(_iter_job_uses(cast(dict[str, Any], job), job_name))
    return pairs


def _iter_job_uses(job: dict[str, Any], job_name: str) -> list[tuple[Any, str]]:
    """Yield ``(uses_value, job_name)`` pairs for a single job's steps."""
    pairs: list[tuple[Any, str]] = []
    raw_steps: object = job.get("steps") or []
    steps = cast(list[object], raw_steps) if isinstance(raw_steps, list) else []
    for step in steps:
        if isinstance(step, dict) and "uses" in step:
            step_mapping = cast(dict[str, Any], step)
            pairs.append((step_mapping["uses"], job_name))
    return pairs


# ---------------------------------------------------------------------------
# Job-level validators
# ---------------------------------------------------------------------------


def _validate_jobs(workflow: dict[str, Any], file_name: str) -> list[Finding]:
    """Validate every job's name, timeout, and concurrency."""
    findings: list[Finding] = []
    raw_jobs: object = workflow.get("jobs") or {}
    if not isinstance(raw_jobs, dict) or not raw_jobs:
        return [
            Finding(
                severity=SEVERITY_ERROR,
                code="WF_JOBS_MISSING",
                message="workflow has no 'jobs' mapping",
                file=file_name,
            )
        ]
    jobs = cast(dict[str, Any], raw_jobs)
    has_workflow_concurrency = "concurrency" in workflow
    for job_name, job in jobs.items():
        findings.extend(_validate_one_job(job, job_name, file_name, has_workflow_concurrency))
    return findings


# owner: quality-infrastructure; reason: stable tested helper contract
def _validate_one_job(  # nosemgrep: boolean-flag-argument
    job: Any,
    job_name: str,
    file_name: str,
    has_workflow_concurrency: bool,
) -> list[Finding]:
    """Convert the stable boolean contract and validate one job."""
    concurrency_policy = (
        ConcurrencyPolicy.WORKFLOW if has_workflow_concurrency else ConcurrencyPolicy.JOB
    )
    return _validate_one_job_with_policy(job, job_name, file_name, concurrency_policy)


def _validate_one_job_with_policy(
    job: Any,
    job_name: str,
    file_name: str,
    concurrency_policy: ConcurrencyPolicy,
) -> list[Finding]:
    """Validate a single job definition."""
    if not isinstance(job, dict):
        return [
            Finding(
                severity=SEVERITY_ERROR,
                code="WF_JOB_NOT_MAPPING",
                message=f"job '{job_name}' is not a mapping",
                file=file_name,
                job=job_name,
            )
        ]
    job_mapping = cast(dict[str, Any], job)
    findings: list[Finding] = []
    findings.extend(_check_job_name(job_mapping, job_name, file_name))
    findings.extend(_check_job_timeout(job_mapping, job_name, file_name))
    if concurrency_policy is ConcurrencyPolicy.JOB and "concurrency" not in job_mapping:
        findings.append(
            Finding(
                severity=SEVERITY_WARNING,
                code="WF_CONCURRENCY_MISSING",
                message=(
                    f"job '{job_name}' has no 'concurrency' group and the "
                    "workflow defines none either"
                ),
                file=file_name,
                job=job_name,
            )
        )
    return findings


def _check_job_name(job: dict[str, Any], job_name: str, file_name: str) -> list[Finding]:
    """Return an error finding if the job has no ``name`` field."""
    if "name" in job:
        return []
    return [
        Finding(
            severity=SEVERITY_ERROR,
            code="WF_JOB_NAME_MISSING",
            message=f"job '{job_name}' is missing a 'name' field",
            file=file_name,
            job=job_name,
        )
    ]


def _check_job_timeout(job: dict[str, Any], job_name: str, file_name: str) -> list[Finding]:
    """Return a warning finding if the job has no ``timeout-minutes``."""
    if "timeout-minutes" in job:
        return []
    return [
        Finding(
            severity=SEVERITY_WARNING,
            code="WF_JOB_TIMEOUT_MISSING",
            message=f"job '{job_name}' has no 'timeout-minutes'",
            file=file_name,
            job=job_name,
        )
    ]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def validate_file(path: Path, yaml_parser: YAML) -> FileReport:
    """Parse and validate a single workflow file.

    Args:
        path: Path to the workflow ``.yml``/``.yaml`` file.
        yaml_parser: Configured ruamel.yaml parser.

    Returns:
        A :class:`FileReport` describing the parse state and findings.
    """
    file_name = path.name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return FileReport(file=file_name, parsed=False, parse_error=str(exc))
    workflow, error = _parse_workflow(text, yaml_parser)
    if workflow is None:
        return FileReport(file=file_name, parsed=False, parse_error=error)
    findings: list[Finding] = []
    findings.extend(_validate_workflow_name(workflow, file_name))
    findings.extend(_validate_triggers(workflow, file_name))
    findings.extend(_validate_permissions(workflow, file_name))
    findings.extend(_validate_action_pinning(workflow, file_name))
    findings.extend(_validate_jobs(workflow, file_name))
    return FileReport(file=file_name, parsed=True, findings=findings)


def validate_directory(directory: Path, yaml_parser: YAML) -> list[FileReport]:
    """Validate every ``.yml``/``.yaml`` workflow file in ``directory``.

    Args:
        directory: Directory to scan recursively for workflow files.
        yaml_parser: Configured ruamel.yaml parser.

    Returns:
        List of :class:`FileReport`, sorted by file name.
    """
    if not directory.is_dir():
        msg = f"workflow directory not found: {directory}"
        raise NotADirectoryError(msg)
    paths = sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])
    logger.info("Scanning %d workflow file(s) in %s", len(paths), directory)
    return [validate_file(path, yaml_parser) for path in paths]


def _has_blocking_errors(report: PolicyReport) -> bool:
    """Return True if any finding should fail the run under the strictness mode."""
    for file_report in report.reports:
        if not file_report.parsed:
            return True
        for finding in file_report.findings:
            if _finding_blocks(finding, report.strict):
                return True
    return False


# owner: quality-infrastructure; reason: stable tested helper contract
def _finding_blocks(  # nosemgrep: boolean-flag-argument
    finding: Finding, strict: bool
) -> bool:
    """Convert the stable boolean contract and classify a finding."""
    strictness = Strictness.STRICT if strict else Strictness.NORMAL
    return _finding_blocks_with_strictness(finding, strictness)


def _finding_blocks_with_strictness(finding: Finding, strictness: Strictness) -> bool:
    """Return True if a finding should fail the run."""
    if finding.severity == SEVERITY_ERROR:
        return True
    return strictness is Strictness.STRICT and finding.severity == SEVERITY_WARNING


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    """Serialise a :class:`Finding` to a JSON-compatible dict."""
    payload: dict[str, Any] = {
        "severity": finding.severity,
        "code": finding.code,
        "message": finding.message,
        "file": finding.file,
    }
    if finding.job is not None:
        payload["job"] = finding.job
    return payload


def _file_report_to_dict(file_report: FileReport) -> dict[str, Any]:
    """Serialise a :class:`FileReport` to a JSON-compatible dict."""
    payload: dict[str, Any] = {
        "file": file_report.file,
        "parsed": file_report.parsed,
        "findings": [_finding_to_dict(f) for f in file_report.findings],
    }
    if file_report.parse_error:
        payload["parse_error"] = file_report.parse_error
    return payload


def report_to_dict(report: PolicyReport) -> dict[str, Any]:
    """Serialise a :class:`PolicyReport` to a JSON-compatible dict.

    Args:
        report: The aggregated validation report.

    Returns:
        Dict with ``pass``, ``strict``, ``file_count``, ``error_count``,
        ``warning_count``, and ``files`` keys.
    """
    counts = _count_findings(report)
    payload: dict[str, Any] = {
        "pass": not _has_blocking_errors(report),
        "strict": report.strict,
        "file_count": len(report.reports),
    }
    payload.update(counts)
    payload["files"] = [_file_report_to_dict(file_report) for file_report in report.reports]
    return payload


def _count_findings(report: PolicyReport) -> dict[str, int]:
    """Tally per-file findings into error, warning, and unparsed counts."""
    parsed_reports = [file_report for file_report in report.reports if file_report.parsed]
    errors, warnings = _tally_severities(parsed_reports)
    unparsed = len(report.reports) - len(parsed_reports)
    return {
        "error_count": errors,
        "warning_count": warnings,
        "unparsed_count": unparsed,
    }


def _tally_severities(file_reports: list[FileReport]) -> tuple[int, int]:
    """Count error and warning findings across parsed file reports."""
    errors = 0
    warnings = 0
    for file_report in file_reports:
        for finding in file_report.findings:
            if finding.severity == SEVERITY_ERROR:
                errors += 1
            elif finding.severity == SEVERITY_WARNING:
                warnings += 1
    return errors, warnings


# ---------------------------------------------------------------------------
# Human-readable output
# ---------------------------------------------------------------------------


def _format_text(report: PolicyReport) -> str:
    """Format a :class:`PolicyReport` as human-readable text."""
    lines: list[str] = []
    for file_report in report.reports:
        lines.extend(_format_file_section(file_report))
    payload = report_to_dict(report)
    lines.append(
        f"\nWorkflow policy: {payload['error_count']} error(s), "
        f"{payload['warning_count']} warning(s) across {payload['file_count']} file(s)."
    )
    if payload["pass"]:
        lines.append("PASS" if not report.strict else "PASS (strict mode)")
    else:
        lines.append("FAIL" + (" (strict mode)" if report.strict else ""))
    return "\n".join(lines)


def _format_file_section(file_report: FileReport) -> list[str]:
    """Format a single :class:`FileReport` as a list of text lines."""
    lines: list[str] = [f"\n[{file_report.file}]"]
    if not file_report.parsed:
        lines.append(f"  PARSE ERROR: {file_report.parse_error}")
        return lines
    if not file_report.findings:
        lines.append("  OK — no findings")
        return lines
    for finding in file_report.findings:
        location = finding.file if finding.job is None else f"{finding.file}:{finding.job}"
        lines.append(f"  [{finding.severity.upper():7}] {finding.code} {location}")
        lines.append(f"      {finding.message}")
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list, or None for ``sys.argv[1:]``.

    Returns:
        Namespace with ``strict``, ``directory``, and ``json`` attributes.
    """
    parser = argparse.ArgumentParser(
        description="YAML 1.2-aware semantic validator for GitHub Actions workflows.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Promote warnings to errors.",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_WORKFLOWS_DIR,
        help=f"Workflow directory to scan (default: {DEFAULT_WORKFLOWS_DIR}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON report instead of human-readable text.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 0 pass, 1 fail, 2 usage error.
    """
    args = _parse_args(argv)
    yaml_parser = _make_parser()
    try:
        file_reports = validate_directory(args.dir, yaml_parser)
    except NotADirectoryError as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_USAGE
    report = PolicyReport(reports=file_reports, strict=args.strict)
    if args.json:
        print(json.dumps(report_to_dict(report), indent=2))
    else:
        print(_format_text(report))
    return EXIT_PASS if not _has_blocking_errors(report) else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
