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
DEFAULT_TIMEOUT_SECONDS = 2100


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


def execute_task(task_id: str, triage_path: Path, report_path: Path, timeout_seconds: int) -> int:
    """Run one task's keyset through the canonical policy and verify coverage.

    Args:
        task_id: Task identifier such as ``T009``.
        triage_path: Path to the recorded triage JSON document.
        report_path: Where the canonical report is written.
        timeout_seconds: Positive wall-clock budget for the mutmut run.

    Returns:
        Canonical policy exit code: 0 clean, 1 findings, 2 tool error.
    """
    if timeout_seconds <= 0:
        msg = "--timeout-seconds must be positive"
        raise TaskPolicyError(msg)
    keys = load_task_keys(triage_path, task_id)
    logger.info("Task %s keyset loaded: %d keys", task_id, len(keys))
    argv = [
        "--scope",
        "selected",
        *(pattern for key in keys for pattern in ("--pattern", key)),
        "--report-path",
        str(report_path),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    exit_code = runner.main(argv)
    if exit_code != policy.EXIT_CLEAN:
        return exit_code
    return _coverage_exit(report_path, task_id, keys)


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
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point returning the canonical policy exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    try:
        return execute_task(args.task, args.triage_path, args.report_path, args.timeout_seconds)
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
