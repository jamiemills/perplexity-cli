"""Run one triage task's surviving-key keyset through the canonical policy.

Loads the task's exact mutant keys from the recorded triage artifact and
delegates to :mod:`scripts.run_mutation` so the canonical fail-closed policy
classifies a fresh selected-scope run over precisely those keys. Exit 0 requires
a policy-clean report whose scope patterns and result count cover every key.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import (  # noqa: E402  # owner: quality-infrastructure; reason: package import follows the direct-script repository-root bootstrap
    mutation_policy as policy,
)
from scripts import (  # noqa: E402  # owner: quality-infrastructure; reason: package import follows the direct-script repository-root bootstrap
    run_mutation as runner,
)

logger = logging.getLogger(__name__)

DEFAULT_TRIAGE_PATH = Path("quality/baselines/mutation-triage.json")
DEFAULT_EXCLUSIONS_PATH = Path("quality/baselines/mutation-task-exclusions.json")
DEFAULT_TIMEOUT_SECONDS = 2100
ALLOWED_DISPOSITIONS = frozenset({"structural-exclusion", "removed-by-simplification"})


class TaskPolicyError(ValueError):
    """Raised when the triage artifact cannot supply a usable keyset."""


def load_task_keys(triage_path: Path, task_id: str) -> tuple[str, ...]:
    """Load one task's sorted surviving-mutant keys from the triage artifact.

    Args:
        triage_path: Path to the recorded triage JSON document.
        task_id: Task identifier such as ``T009``.

    Returns:
        Sorted tuple of exact mutant names owned by the task.

    Raises:
        TaskPolicyError: If the artifact is unreadable, malformed, or the
            task is missing or holds an empty keyset.
    """
    document = _read_triage(triage_path)
    entry = _find_task(document, task_id)
    raw_keys = entry.get("keys")
    if not isinstance(raw_keys, list):
        msg = f"task {task_id} keyset is malformed"
        raise TaskPolicyError(msg)
    keys = tuple(sorted(str(key) for key in cast("list[object]", raw_keys)))
    if not keys:
        msg = f"task {task_id} has an empty keyset"
        raise TaskPolicyError(msg)
    return keys


def load_exclusions(exclusions_path: Path, task_id: str, keys: tuple[str, ...]) -> dict[str, str]:
    """Load this task's documented exclusions keyed by baseline mutant name.

    Args:
        exclusions_path: Path to the recorded exclusions JSON document.
        task_id: Task identifier whose entries are selected.
        keys: The task's full baseline keyset, used to reject unknown names.

    Returns:
        Mapping of baseline key to its recorded disposition.

    Raises:
        TaskPolicyError: If the document is malformed, an entry lacks
            owner/reason/proof, or names a key outside the task keyset.
    """
    if not exclusions_path.exists():
        return {}
    raw = _read_exclusions(exclusions_path)
    known = frozenset(keys)
    exclusions: dict[str, str] = {}
    for entry in cast("list[object]", raw["entries"]):
        record = _validated_entry(entry)
        if record["task"] != task_id:
            continue
        key = record["key"]
        if key not in known:
            msg = f"exclusion for {key} does not belong to {task_id}"
            raise TaskPolicyError(msg)
        exclusions[key] = record["disposition"]
    return dict(sorted(exclusions.items()))


def verify_report_coverage(payload: dict[str, object], keys: tuple[str, ...]) -> list[str]:
    """Return coverage disagreements between a canonical report and a keyset.

    Args:
        payload: Parsed canonical mutation-report payload.
        keys: Exact mutant names the run was expected to classify.

    Returns:
        Sorted disagreement descriptions; empty means fully covered and clean.
    """
    issues: list[str] = []
    if _scope_patterns(payload) != frozenset(keys):
        issues.append("report scope patterns do not equal the task keyset")
    if payload.get("status") != policy.STATUS_CLEAN:
        issues.append(f"report status is {payload.get('status')!r}, expected clean")
    total = payload.get("total_mutants")
    if not isinstance(total, int) or total != len(keys):
        issues.append(f"total_mutants {total!r} != keyset size {len(keys)}")
    return sorted(issues)


@dataclass(frozen=True, slots=True)
class TaskRunSpec:
    """Immutable inputs for one task-policy execution."""

    task_id: str
    triage_path: Path = DEFAULT_TRIAGE_PATH
    report_path: Path = Path("build/reports/mutation-task-report.json")
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    exclusions_path: Path = DEFAULT_EXCLUSIONS_PATH


def execute_task(spec: TaskRunSpec) -> int:
    """Run one task's keyset through the canonical policy and verify coverage.

    Args:
        spec: Immutable execution inputs.

    Returns:
        Canonical policy exit code: 0 clean, 1 findings, 2 tool error.
    """
    if spec.timeout_seconds <= 0:
        msg = "--timeout-seconds must be positive"
        raise TaskPolicyError(msg)
    keys = load_task_keys(spec.triage_path, spec.task_id)
    exclusions = load_exclusions(spec.exclusions_path, spec.task_id, keys)
    required = tuple(key for key in keys if key not in exclusions)
    logger.info(
        "Task %s keyset loaded: %d keys (%d documented exclusions)",
        spec.task_id,
        len(keys),
        len(keys) - len(required),
    )
    exit_code = _run_selected(required, spec.report_path, spec.timeout_seconds)
    if exit_code != policy.EXIT_CLEAN:
        return exit_code
    return _coverage_exit(spec.report_path, spec.task_id, required)


def _run_selected(required: tuple[str, ...], report_path: Path, timeout_seconds: int) -> int:
    """Run the required keyset through the canonical selected-scope policy."""
    argv = [
        "--scope",
        "selected",
        *(pattern for key in required for pattern in ("--pattern", key)),
        "--report-path",
        str(report_path),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    return runner.main(argv)


def _read_exclusions(path: Path) -> dict[str, object]:
    """Load the exclusions document, failing closed on unreadable content."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"unreadable exclusions artifact: {path}"
        raise TaskPolicyError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"malformed exclusions artifact: {path}"
        raise TaskPolicyError(msg)
    document = cast("dict[str, object]", raw)
    if not isinstance(document.get("entries"), list):
        msg = f"malformed exclusions artifact: {path}"
        raise TaskPolicyError(msg)
    return document


def _provenance_gaps(record: dict[str, object]) -> list[str]:
    """Return required provenance fields that are missing or blank."""
    return [
        field
        for field in ("task", "key", "disposition", "owner", "reason", "proof")
        if not isinstance(record.get(field), str) or not cast("str", record.get(field)).strip()
    ]


def _validated_entry(raw_entry: object) -> dict[str, str]:
    """Validate one exclusion record, requiring full provenance fields."""
    if not isinstance(raw_entry, dict):
        msg = "exclusion entry is not an object"
        raise TaskPolicyError(msg)
    record = cast("dict[str, object]", raw_entry)
    gaps = _provenance_gaps(record)
    disposition = str(record.get("disposition"))
    if gaps or disposition not in ALLOWED_DISPOSITIONS:
        msg = f"exclusion entry for {record.get('key')!r} lacks provenance or valid disposition"
        raise TaskPolicyError(msg)
    return {
        field: str(record.get(field))
        for field in ("task", "key", "disposition", "owner", "reason", "proof")
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse task-policy CLI arguments.

    Args:
        argv: Argument list, or None for ``sys.argv[1:]``.

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, help="Triage task id, e.g. T009")
    parser.add_argument("--triage-path", type=Path, default=DEFAULT_TRIAGE_PATH)
    parser.add_argument("--exclusions-path", type=Path, default=DEFAULT_EXCLUSIONS_PATH)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point returning the canonical policy exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    try:
        return execute_task(
            TaskRunSpec(
                task_id=args.task,
                triage_path=args.triage_path,
                report_path=args.report_path,
                timeout_seconds=args.timeout_seconds,
                exclusions_path=args.exclusions_path,
            )
        )
    except TaskPolicyError as exc:
        logger.exception("%s", exc)
        return policy.EXIT_TOOL_ERROR


def _read_triage(path: Path) -> dict[str, object]:
    """Load the triage document, failing closed on unreadable content."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"unreadable triage artifact: {path}"
        raise TaskPolicyError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"malformed triage artifact: {path}"
        raise TaskPolicyError(msg)
    document = cast("dict[str, object]", raw)
    if not isinstance(document.get("tasks"), list):
        msg = f"malformed triage artifact: {path}"
        raise TaskPolicyError(msg)
    return document


def _find_task(document: dict[str, object], task_id: str) -> dict[str, object]:
    """Return the requested task entry or fail closed."""
    tasks = cast("list[object]", document["tasks"])
    for raw_entry in tasks:
        if not isinstance(raw_entry, dict):
            continue
        entry = cast("dict[str, object]", raw_entry)
        if entry.get("task_id") == task_id:
            return entry
    msg = f"task {task_id} missing from triage artifact"
    raise TaskPolicyError(msg)


def _scope_patterns(payload: dict[str, object]) -> frozenset[str]:
    """Extract the reported scope pattern set, tolerating malformed scopes."""
    scope = payload.get("scope")
    if not isinstance(scope, dict):
        return frozenset()
    raw_patterns = cast("dict[str, object]", scope).get("patterns", ())
    if not isinstance(raw_patterns, list):
        return frozenset()
    return frozenset(str(pattern) for pattern in cast("list[object]", raw_patterns))


def _coverage_exit(report_path: Path, task_id: str, keys: tuple[str, ...]) -> int:
    """Verify the clean report covers every key and map to an exit code."""
    payload = cast("dict[str, object]", json.loads(report_path.read_text(encoding="utf-8")))
    issues = verify_report_coverage(payload, keys)
    for issue in issues:
        logger.error("Task %s coverage: %s", task_id, issue)
    return policy.EXIT_CLEAN if not issues else policy.EXIT_TOOL_ERROR


if __name__ == "__main__":
    sys.exit(main())
