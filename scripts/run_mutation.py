"""Canonical fresh-run mutation orchestrator.

Refuses stale workspaces, verifies the installed Mutmut environment,
executes Mutmut in a controlled process group, aggregates independent
generated/result evidence and always publishes a schema-valid report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess  # nosec B404  # owner: quality-infrastructure; reason: internally assembled argv without a shell
import sys
import time
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import (  # noqa: E402  # owner: quality-infrastructure; reason: package import follows the direct-script repository-root bootstrap
    mutation_policy as policy,
)
from scripts.mutation_environment import (  # noqa: E402  # owner: quality-infrastructure; reason: package import follows the direct-script repository-root bootstrap
    EnvironmentMismatchError,
    verify_environment,
)
from scripts.mutation_evidence import (  # noqa: E402  # owner: quality-infrastructure; reason: package import follows the direct-script repository-root bootstrap
    MutationSelection,
    SourceDocument,
    StructuralExclusion,
    enumerate_generated_mutants,
)
from scripts.mutation_process import (  # noqa: E402  # owner: quality-infrastructure; reason: package import follows the direct-script repository-root bootstrap
    launch_mutmut,
)

logger = logging.getLogger(__name__)

MUTANTS_DIRNAME = "mutants"
GENERATED_SOURCE_ROOT = "src"
SOURCE_PACKAGE_DIR = PROJECT_ROOT / "src"
_SOURCE_PREFIX = "src/perplexity_cli/"
EXCLUSIONS_PATH = PROJECT_ROOT / "quality" / "mutation-exclusions.toml"
FULL_TIMEOUT_CAP_S = 19_800
SELECTED_TIMEOUT_CAP_S = 2_100
REPORT_RESERVE_S = 120
PUBLICATION_RESERVE_BY_SCOPE: dict[str, int] = {"full": 600, "selected": 300}
TERMINATION_GRACE_S = 5
DeclarationKindLiteral = Literal["abstract-method", "protocol-method"]

_CANDIDATE_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class RunnerUsageError(ValueError):
    """Raised when requested run arguments are invalid."""


class StaleWorkspaceError(RuntimeError):
    """Raised when a previous mutants workspace already exists."""


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Validated request for one fresh mutation run."""

    selection: MutationSelection
    report_path: Path
    timeout_seconds: int
    outer_deadline_epoch: int | None
    candidate_sha: str | None
    allow_empty_diff: bool


def _lexists(path: Path) -> bool:
    """Return whether any filesystem entry exists at ``path``."""
    return os.path.lexists(path)


def _module_pattern(relative_source: str) -> str:
    """Convert a production source path into a boundary-safe mutant pattern.

    Args:
        relative_source: Path such as ``src/perplexity_cli/api/client.py``.

    Returns:
        A Mutmut mutant-name glob ending in ``x*``.

    Raises:
        RunnerUsageError: If the path is outside the production package.
    """
    if not relative_source.startswith(_SOURCE_PREFIX) or not relative_source.endswith(".py"):
        msg = f"changed path is not production source: {relative_source}"
        raise RunnerUsageError(msg)
    segments = relative_source[len(_SOURCE_PREFIX) : -len(".py")].split("/")
    if _has_non_module_segments(segments):
        msg = f"changed path has non-module segments: {relative_source}"
        raise RunnerUsageError(msg)
    if segments[-1] == "__init__":
        segments.pop()
    return ".".join(("perplexity_cli", *segments)) + ".x*"


def _has_non_module_segments(segments: list[str]) -> bool:
    """Return whether any path segment cannot form a dotted module part."""
    return any(not segment.isidentifier() for segment in segments)


def patterns_from_manifest(manifest_path: Path) -> tuple[str, ...]:
    """Build selected patterns from a discovery JSON manifest.

    Args:
        manifest_path: Path to a discovery manifest JSON document.

    Returns:
        One pattern per changed production source file.

    Raises:
        RunnerUsageError: If the manifest is malformed or has no targets.
    """
    changed = _manifest_changed_files(manifest_path)
    return tuple(_module_pattern(entry) for entry in changed)


def _manifest_changed_files(manifest_path: Path) -> list[str]:
    """Load and validate the ``changed_files`` list of a discovery manifest."""
    payload = _manifest_payload(manifest_path)
    changed_any: object = payload.get("changed_files")
    if not isinstance(changed_any, list) or not changed_any:
        msg = "discovery manifest lacks a non-empty changed_files list"
        raise RunnerUsageError(msg)
    return _validated_string_entries(cast("list[object]", changed_any))


def _manifest_payload(manifest_path: Path) -> dict[str, object]:
    """Read one discovery manifest as a JSON dictionary."""
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"unreadable discovery manifest: {manifest_path}"
        raise RunnerUsageError(msg) from exc
    if not isinstance(payload, dict):
        msg = "discovery manifest is not a JSON object"
        raise RunnerUsageError(msg)
    return cast("dict[str, object]", payload)


def _validated_string_entries(entries: list[object]) -> list[str]:
    """Validate that every manifest entry is a non-empty string path."""
    if not all(isinstance(item, str) for item in entries):
        msg = "discovery manifest changed_files entries must be strings"
        raise RunnerUsageError(msg)
    return cast("list[str]", entries)


def resolve_budget(request: RunRequest, setup_started: float) -> int:
    """Derive the allowable subprocess budget from caps and deadline reserves.

    Args:
        request: Validated run request.
        setup_started: Monotonic timestamp captured before setup work.

    Returns:
        Effective subprocess budget in seconds.

    Raises:
        RunnerUsageError: If caps are exceeded or the budget is exhausted.
    """
    cap = FULL_TIMEOUT_CAP_S if request.selection.scope == "full" else SELECTED_TIMEOUT_CAP_S
    if request.timeout_seconds > cap:
        msg = f"requested timeout exceeds {cap}s cap for {request.selection.scope} scope"
        raise RunnerUsageError(msg)
    budget = request.timeout_seconds
    if request.outer_deadline_epoch is not None:
        reserve = REPORT_RESERVE_S + PUBLICATION_RESERVE_BY_SCOPE[request.selection.scope]
        remaining = int(request.outer_deadline_epoch - time.time()) - reserve
        logger.info("Outer deadline leaves %ss before publication reserve", remaining)
        budget = min(budget, remaining)
    if budget <= 0:
        msg = "outer deadline exhausted before the mutation run could start"
        raise RunnerUsageError(msg)
    del setup_started
    return budget


def _git_output(arguments: tuple[str, ...]) -> str:
    """Run Git with assembled argv and return stripped stdout."""
    from scripts.mutation_environment import EnvironmentMismatchError

    result = subprocess.run(  # nosec B603  # owner: quality-infrastructure; reason: fixed git argv without a shell
        ("git", *arguments),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        msg = f"git {arguments[0]} failed with status {result.returncode}"
        raise EnvironmentMismatchError(msg)
    return result.stdout.strip()


def collect_generated_keys() -> tuple[str, ...]:
    """Enumerate generated mutant keys from the fresh workspace."""
    keys: list[str] = []
    generated_root = PROJECT_ROOT / MUTANTS_DIRNAME / GENERATED_SOURCE_ROOT
    for source_path in sorted(generated_root.rglob("*.py")):
        if "__pycache__" in source_path.parts:
            continue
        relative = source_path.relative_to(PROJECT_ROOT)
        evidence = enumerate_generated_mutants(source_path.read_text(encoding="utf-8"), relative)
        keys.extend(evidence.keys)
        disagreements = EvidenceCarrier(evidence.dictionary_disagreements)
        if disagreements.issues:
            msg = f"generated dictionary disagreement in {relative}"
            raise EnvironmentMismatchError(msg)
    return tuple(keys)


class EvidenceCarrier:
    """Small truthiness carrier keeping helper signatures within limits."""

    def __init__(self, issues: Iterable[str]) -> None:
        self.issues = tuple(issues)


def _load_exclusion_manifest() -> tuple[StructuralExclusion, ...]:
    """Load reviewed structural exclusion declarations, if configured."""
    if not EXCLUSIONS_PATH.is_file():
        return ()
    payload = tomllib.loads(EXCLUSIONS_PATH.read_text(encoding="utf-8"))
    entries = payload.get("exclusion", [])
    return tuple(
        StructuralExclusion(
            source_path=str(entry["source_path"]),
            line=int(entry["line"]),
            declaration=str(entry["declaration"]),
            declaration_kind=_validated_kind(str(entry["declaration_kind"])),
            owner=str(entry["owner"]),
            reason=str(entry["reason"]),
            reviewer=str(entry["reviewer"]),
        )
        for entry in entries
    )


def structural_disagreements() -> tuple[str, ...]:
    """Validate exact pragma exclusions against production sources."""
    sources = tuple(
        SourceDocument(path.relative_to(PROJECT_ROOT).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(SOURCE_PACKAGE_DIR.rglob("*.py"))
        if "__pycache__" not in path.parts
    )
    from scripts.mutation_evidence import validate_structural_exclusions

    return validate_structural_exclusions(sources, _load_exclusion_manifest())


def _provenance(candidate_sha: str | None) -> policy.Provenance:
    """Build current source provenance, optionally pinning the candidate."""
    revision = _git_output(("rev-parse", "HEAD"))
    if candidate_sha is not None and candidate_sha != revision:
        msg = "candidate SHA does not match the checked-out revision"
        raise RunnerUsageError(msg)
    tree = _git_output(("rev-parse", "HEAD^{tree}"))
    return policy.Provenance(revision, tree, UNKNOWN_FINGERPRINT, True)


UNKNOWN_FINGERPRINT = "unknown"


def _fingerprint(results_text: str, generated_keys: tuple[str, ...]) -> str:
    """Digest the exact tracked inputs of this classification."""
    payload = results_text + "\0" + "\n".join(sorted(generated_keys))
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(slots=True)
class RunInputs:
    """Aggregated pure inputs ready for canonical classification."""

    context: policy.ReportContext
    generated_keys: tuple[str, ...]
    disagreements: policy.EvidenceDisagreements = field(
        default_factory=policy.EvidenceDisagreements
    )
    results_text: str = ""


def gather_inputs(request: RunRequest, environment: policy.EnvironmentIdentity) -> RunInputs:
    """Collect all independent evidence after a completed Mutmut run."""
    version = policy.detect_version()
    results_text = policy.fetch_results_text()
    generated_keys = collect_generated_keys()
    selection = request.selection
    provenance = _provenance(request.candidate_sha)
    fingerprint = _fingerprint(results_text, generated_keys)
    provenance = policy.Provenance(
        provenance.source_revision, provenance.source_tree, fingerprint, True
    )
    context = policy.ReportContext(version, selection, provenance, environment, "completed")
    disagreements = policy.EvidenceDisagreements(dictionary=structural_disagreements())
    return RunInputs(context, generated_keys, disagreements, results_text)


def _failure_report(selection: MutationSelection, message: str) -> policy.MutationReport:
    """Build a placeholder-context tool-error report for controlled failures."""
    return policy.build_tool_error_report(policy.placeholder_context(selection), message)


def _log_failure(kind: str) -> None:
    """Log one controlled failure kind without reflecting its payload."""
    logger.error("mutation run failed: %s", kind)


def _validated_kind(raw: str) -> DeclarationKindLiteral:
    """Validate a manifest declaration kind against supported literals."""
    if raw == "abstract-method":
        return "abstract-method"
    if raw == "protocol-method":
        return "protocol-method"
    msg = f"unsupported exclusion declaration kind: {raw}"
    raise RunnerUsageError(msg)


def _is_empty_selected(request: RunRequest) -> bool:
    """Return whether this is the sole allowed empty-diff not-applicable case."""
    return (
        request.allow_empty_diff
        and request.selection.scope == "selected"
        and not request.selection.patterns
    )


def _run_inner(request: RunRequest, setup_started: float) -> int:
    """Perform the verified run and canonical classification."""
    if _is_empty_selected(request):
        return _write_empty_diff_report(request)
    environment = verify_environment()
    budget = resolve_budget(request, setup_started)
    launch_mutmut(request.selection.patterns, budget)
    inputs = gather_inputs(request, environment)
    return policy.run_policy(
        policy.PolicyInput(
            inputs.context, inputs.generated_keys, inputs.disagreements, inputs.results_text
        ),
        request.report_path,
    )


def _write_empty_diff_report(request: RunRequest) -> int:
    """Publish the sole allowed not-applicable report without launching Mutmut."""
    version = policy.detect_version()
    provenance = _provenance(request.candidate_sha)
    fingerprint = _fingerprint("", ())
    context = policy.ReportContext(
        version,
        request.selection,
        policy.Provenance(provenance.source_revision, provenance.source_tree, fingerprint, True),
        verify_environment(),
        "not-applicable",
    )
    payload = policy.report_to_dict(policy.build_tool_error_report(context, ""))
    payload["status"] = policy.STATUS_NOT_APPLICABLE
    payload.pop("error", None)
    policy.validate_report_payload(payload)
    request.report_path.parent.mkdir(parents=True, exist_ok=True)
    request.report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    logger.info("Empty diff: mutation run is not applicable")
    return policy.EXIT_CLEAN


def execute(request: RunRequest, setup_started: float) -> int:
    """Execute one fresh classified mutation run.

    Args:
        request: Validated run request.
        setup_started: Monotonic timestamp captured by the CLI entry point.

    Returns:
        Canonical policy exit code (0 clean/not-applicable, 1 findings,
        2 tool/configuration error).
    """
    if _lexists(PROJECT_ROOT / MUTANTS_DIRNAME):
        logger.error("refusing stale workspace at %s/", MUTANTS_DIRNAME)
        return policy.EXIT_TOOL_ERROR
    try:
        return _run_inner(request, setup_started)
    except (RunnerUsageError, StaleWorkspaceError, EnvironmentMismatchError, OSError) as exc:
        kind = type(exc).__name__
        _log_failure(kind)
        policy.write_report(_failure_report(request.selection, kind), request.report_path)
        return policy.EXIT_TOOL_ERROR


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse runner CLI arguments.

    Args:
        argv: Argument list, or None for ``sys.argv[1:]``.

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("full", "selected"), required=True)
    parser.add_argument("--pattern", action="append", default=[])
    parser.add_argument("--manifest-path", type=Path, default=None)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    parser.add_argument("--outer-deadline-epoch", type=int, default=None)
    parser.add_argument("--candidate-sha", default=None)
    parser.add_argument("--allow-empty-diff", action="store_true")
    return parser.parse_args(argv)


def _reject_conflicting_selection(args: argparse.Namespace) -> None:
    """Reject declaring both explicit patterns and a manifest path."""
    if args.pattern and args.manifest_path is not None:
        msg = "--pattern and --manifest-path are mutually exclusive"
        raise RunnerUsageError(msg)


def _validate_common(args: argparse.Namespace) -> None:
    """Validate scope-independent argument invariants."""
    if args.timeout_seconds <= 0:
        msg = "--timeout-seconds must be positive"
        raise RunnerUsageError(msg)
    if args.candidate_sha is not None and not _CANDIDATE_SHA_PATTERN.fullmatch(args.candidate_sha):
        msg = "--candidate-sha must be a lowercase 40-hex SHA"
        raise RunnerUsageError(msg)


def _empty_selection() -> MutationSelection:
    """Build the single sanctioned empty selected-scope marker.

    ``MutationSelection`` normally rejects an empty pattern list; the sole
    allowed exception is the explicit not-applicable empty-diff case, whose
    selection is never used for matching or classification.
    """
    selection = object.__new__(MutationSelection)
    object.__setattr__(selection, "scope", "selected")
    object.__setattr__(selection, "patterns", ())
    return selection


def build_request(args: argparse.Namespace, manifest_patterns: tuple[str, ...]) -> RunRequest:
    """Validate parsed arguments into a :class:`RunRequest`.

    Raises:
        RunnerUsageError: On any invalid combination.
    """
    _validate_common(args)
    if args.scope == "selected":
        return _build_selected_request(args, manifest_patterns)
    if args.pattern or args.manifest_path is not None:
        msg = "full scope cannot declare selected patterns"
        raise RunnerUsageError(msg)
    return _request(args, MutationSelection(args.scope, ()))


def _build_selected_request(
    args: argparse.Namespace, manifest_patterns: tuple[str, ...]
) -> RunRequest:
    """Build a validated selected-scope request, including the empty case."""
    _reject_conflicting_selection(args)
    patterns = tuple(args.pattern) if args.pattern else manifest_patterns
    if patterns:
        return _request(args, MutationSelection("selected", patterns))
    if args.allow_empty_diff:
        return _request(args, _empty_selection())
    msg = "selected scope requires at least one pattern"
    raise RunnerUsageError(msg)


def _request(args: argparse.Namespace, selection: MutationSelection) -> RunRequest:
    """Assemble the immutable run request from validated parts."""
    return RunRequest(
        selection=selection,
        report_path=args.report_path,
        timeout_seconds=args.timeout_seconds,
        outer_deadline_epoch=args.outer_deadline_epoch,
        candidate_sha=args.candidate_sha,
        allow_empty_diff=args.allow_empty_diff,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point returning the canonical policy exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    setup_started = time.monotonic()
    manifest_patterns: tuple[str, ...] = ()
    if args.manifest_path is not None:
        manifest_patterns = _manifest_or_fail(args)
    return execute(_request_or_fail(args, manifest_patterns), setup_started)


def _manifest_or_fail(args: argparse.Namespace) -> tuple[str, ...]:
    """Load manifest patterns or exit via a controlled usage failure."""
    try:
        return patterns_from_manifest(args.manifest_path)
    except RunnerUsageError as exc:
        _usage_exit(exc)
        unreachable = AssertionError("unreachable")
        raise unreachable from exc


def _request_or_fail(args: argparse.Namespace, manifest_patterns: tuple[str, ...]) -> RunRequest:
    """Build the validated request or exit via a controlled usage failure."""
    try:
        return build_request(args, manifest_patterns)
    except RunnerUsageError as exc:
        _usage_exit(exc)
        unreachable = AssertionError("unreachable")
        raise unreachable from exc


def _usage_exit(failure: RunnerUsageError) -> None:
    """Log one usage failure and exit with the tool-error code."""
    logger.error("%s", failure)
    sys.exit(policy.EXIT_TOOL_ERROR)


if __name__ == "__main__":
    sys.exit(main())
