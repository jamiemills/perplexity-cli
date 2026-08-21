"""Canonical fresh-run mutation orchestrator.

Refuses stale workspaces, verifies the installed Mutmut environment,
executes Mutmut in a controlled process group, aggregates independent
generated/result evidence and always publishes a schema-valid report.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import logging
import os
import platform
import re
import signal
import subprocess  # nosec B404  # owner: quality-infrastructure; reason: internally assembled argv without a shell
import sys
import time
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType
from typing import Any, Literal, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import (  # noqa: E402  # owner: quality-infrastructure; reason: package import follows the direct-script repository-root bootstrap
    mutation_policy as policy,
)
from scripts.mutation_evidence import (  # noqa: E402  # owner: quality-infrastructure; reason: package import follows the direct-script repository-root bootstrap
    MutationSelection,
    SourceDocument,
    StructuralExclusion,
    enumerate_generated_mutants,
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
_CANDIDATE_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SANITISED_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV")


class RunnerUsageError(ValueError):
    """Raised when requested run arguments are invalid."""


class StaleWorkspaceError(RuntimeError):
    """Raised when a previous mutants workspace already exists."""


class EnvironmentMismatchError(RuntimeError):
    """Raised when the installed Mutmut environment cannot be verified."""


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


def _git_output(arguments: tuple[str, ...]) -> str:
    """Run Git with assembled argv and return stripped stdout."""
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


def _file_digest(path: Path) -> str:
    """Return the SHA-256 digest of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_record_entries(dist_root: Path, record: Path) -> tuple[dict[str, str], frozenset[str]]:
    """Hash every digest-bearing RECORD entry against actual bytes.

    Args:
        dist_root: Installed distribution root directory.
        record: Path to the dist-info ``RECORD`` file.

    Returns:
        Mapping of relative path to verified SHA-256 plus the full set of
        recorded paths (including digest-free entries such as ``RECORD``).

    Raises:
        EnvironmentMismatchError: If an entry is missing or tampered.
    """
    verified: dict[str, str] = {}
    listed: set[str] = set()
    for line in record.read_text(encoding="utf-8").splitlines():
        relative, expected, _size = line.rsplit(",", 2)
        listed.add(relative)
        if not expected:
            continue
        target = dist_root / relative
        if not target.is_file():
            msg = f"installed Mutmut file is missing: {relative}"
            raise EnvironmentMismatchError(msg)
        encoded = base64.urlsafe_b64encode(hashlib.sha256(target.read_bytes()).digest())
        if f"sha256={encoded.rstrip(b'=').decode()}" != expected:
            msg = f"installed Mutmut file is tampered: {relative}"
            raise EnvironmentMismatchError(msg)
        verified[relative] = _file_digest(target)
    return verified, frozenset(listed)


def _reject_unlisted_files(dist_root: Path, record: Path, listed: frozenset[str]) -> None:
    """Fail when installed Mutmut files are absent from ``RECORD``."""
    for parent in (dist_root / "mutmut", record.parent):
        for candidate in sorted(parent.rglob("*")):
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(dist_root).as_posix()
            if relative not in listed:
                msg = f"installed Mutmut file is not recorded: {relative}"
                raise EnvironmentMismatchError(msg)


def _find_record() -> tuple[Path, Path]:
    """Locate the installed Mutmut distribution root and its RECORD file."""
    dist_info = f"mutmut-{policy.LOCKED_MUTMUT_VERSION}.dist-info"
    for entry in sys.path:
        record = Path(entry) / dist_info / "RECORD"
        if record.is_file():
            return record.parent.parent, record
    msg = f"Mutmut {dist_info} RECORD was not found on sys.path"
    raise EnvironmentMismatchError(msg)


def _distribution_identity() -> tuple[str, str]:
    """Verify the installed Mutmut tree and return its digests."""
    dist_root, record = _find_record()
    installed_version = importlib.metadata.version("mutmut")
    if installed_version != policy.LOCKED_MUTMUT_VERSION:
        msg = f"Mutmut version {installed_version} is not locked {policy.LOCKED_MUTMUT_VERSION}"
        raise EnvironmentMismatchError(msg)
    verified, listed = _verify_record_entries(dist_root, record)
    _reject_unlisted_files(dist_root, record, listed)
    record_digest = hashlib.sha256(record.read_bytes()).hexdigest()
    combined = "".join(f"{path}\0{digest}\n" for path, digest in sorted(verified.items()))
    return hashlib.sha256(combined.encode()).hexdigest(), record_digest


def _uv_version() -> str:
    """Return the installed uv version string."""
    result = subprocess.run(  # nosec B603  # owner: quality-infrastructure; reason: fixed uv argv without a shell
        ("uv", "--version"),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        msg = f"uv --version failed with status {result.returncode}"
        raise EnvironmentMismatchError(msg)
    return result.stdout.strip()


def _installed_distributions_digest() -> str:
    """Digest the sorted installed distribution inventory."""
    inventory = sorted(
        f"{dist.metadata['Name']}\0{dist.version}"
        for dist in importlib.metadata.distributions()
        if dist.metadata.get("Name")
    )
    payload = "".join(f"{entry}\n" for entry in inventory)
    return hashlib.sha256(payload.encode()).hexdigest()


def verify_environment() -> policy.EnvironmentIdentity:
    """Verify installed Mutmut and build authoritative environment identity.

    Returns:
        Complete environment identity for provenance-bound reports.

    Raises:
        EnvironmentMismatchError: If verification fails.
    """
    mutmut_digest, record_digest = _distribution_identity()
    return policy.EnvironmentIdentity(
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        python_cache_tag=sys.implementation.cache_tag,
        platform=platform.platform(terse=True),
        uv_version=_uv_version(),
        installed_distributions_digest=_installed_distributions_digest(),
        mutmut_distribution_digest=mutmut_digest,
        mutmut_record_digest=record_digest,
        locked_wheel_filename=policy.LOCKED_WHEEL_FILENAME,
        locked_wheel_sha256=policy.LOCKED_WHEEL_SHA256,
    )


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


def _sanitised_environment() -> dict[str, str]:
    """Build a minimal credential-free, offline-forced child environment."""
    source = os.environ
    child = {key: source[key] for key in _SANITISED_ENV_KEYS if key in source}
    child["UV_OFFLINE"] = "1"
    return child


def _termination_grace_s() -> int:
    """Return the bounded teardown grace period before SIGKILL."""
    return TERMINATION_GRACE_S


def _terminate_process_group(process_group_id: int) -> None:
    """Terminate then kill one process group after a grace period."""
    for send in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process_group_id, send)
        except ProcessLookupError:
            return
        if send == signal.SIGTERM:
            time.sleep(_termination_grace_s())


class _SignalForwarder:
    """Forward termination signals to the mutation process group."""

    def __init__(self) -> None:
        self.process_group_id: int | None = None

    def __call__(self, signum: int, _frame: FrameType | None) -> None:
        if self.process_group_id is not None:
            _terminate_process_group(self.process_group_id)
            self._exit(signum)

    @staticmethod
    def _exit(signum: int) -> None:
        forwarded = f"forwarded signal {signum} to the mutation group"
        raise SystemExit(forwarded)


def launch_mutmut(argv_suffix: tuple[str, ...], budget: int) -> None:
    """Run Mutmut inside its own process group with a hard budget.

    Args:
        argv_suffix: Arguments after ``run`` (patterns for selected scope).
        budget: Maximum seconds before controlled termination.

    Raises:
        EnvironmentMismatchError: On timeout or non-zero Mutmut exit.
    """
    command = (*policy.MUTMUT_PREFIX, "run", *argv_suffix)
    logger.info("Running %s with %ss budget", " ".join(command), budget)
    forwarder = _SignalForwarder()
    process = subprocess.Popen(  # nosec B603  # owner: quality-infrastructure; reason: pinned mutmut argv without a shell
        command,
        cwd=PROJECT_ROOT,
        env=_sanitised_environment(),
        start_new_session=True,
    )
    forwarder.process_group_id = os.getpgid(process.pid)
    previous = _install_forwarders(forwarder)
    try:
        returncode = process.wait(timeout=budget)
        _raise_on_infrastructure_exit(returncode)
    except subprocess.TimeoutExpired:
        _log_timeout(budget)
        _terminate_process_group(forwarder.process_group_id)
        msg = f"mutation run timed out after {budget}s"
        raise EnvironmentMismatchError(msg) from None
    finally:
        signal.signal(signal.SIGINT, previous[signal.SIGINT])
        signal.signal(signal.SIGTERM, previous[signal.SIGTERM])
        if process.poll() is None:
            _terminate_process_group(forwarder.process_group_id)
            process.kill()
            process.wait()


def _install_forwarders(forwarder: _SignalForwarder) -> dict[int, Any]:
    """Install SIGINT/SIGTERM forwarders and return the previous handlers."""
    signums: tuple[int, int] = (signal.SIGINT, signal.SIGTERM)
    previous: dict[int, Any] = {signum: signal.getsignal(signum) for signum in signums}
    for signum in signums:
        signal.signal(signum, forwarder)
    return previous


def _raise_on_infrastructure_exit(returncode: int) -> None:
    """Treat any Mutmut exit beyond clean/findings as an infrastructure error."""
    if returncode not in (0, 1):
        msg = f"mutmut exited with status {returncode}"
        raise EnvironmentMismatchError(msg)


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


def _log_timeout(budget: int) -> None:
    """Log a budget overrun before group termination."""
    logger.error("Mutation run exceeded its %ss budget; terminating group", budget)


_DECLARATION_KINDS = ("abstract-method", "protocol-method")
DeclarationKindLiteral = Literal["abstract-method", "protocol-method"]


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
