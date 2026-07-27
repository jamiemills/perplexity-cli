"""Static policy tests for GitHub workflow configuration.

The original raw-text scanning is retained for the cross-workflow rules
(external-action pinning and JavaScript-runtime opt-out) where the literal
text is the contract.  Topology assertions — concurrency, timeouts,
``needs:`` wiring, the trusted Safety guard, and the Scorecard producer
permissions — now parse the YAML 1.2 structure via :mod:`ruamel.yaml` so
that key collisions, indentation, and reference shape are validated
semantically rather than as plain text.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from ruamel.yaml import YAML

if TYPE_CHECKING:
    from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"

EXTERNAL_USE = re.compile(r"^\s*uses:\s*(?!\./)(\S+)", re.MULTILINE)
PINNED_USE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")

SCHEDULED_WORKFLOWS: tuple[str, ...] = (
    "mutation-scheduled.yml",
    "scorecard.yml",
    "semgrep-advisory.yml",
)

_NO_CONTINUE_ON_ERROR_WORKFLOWS: tuple[str, ...] = (
    "mutation-scheduled.yml",
    "semgrep-advisory.yml",
)


def _workflow_texts() -> dict[str, str]:
    """Return a mapping of workflow file name to its raw text contents."""
    return {
        path.name: path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.y*ml"))
    }


def _make_parser() -> YAML:
    """Build a strict ruamel.yaml parser that rejects duplicate mapping keys."""
    parser = YAML(typ="safe")
    parser.allow_duplicate_keys = False
    return parser


def _load_workflow(name: str) -> dict[str, Any]:
    """Parse workflow ``name`` into a dict using the strict YAML 1.2 parser."""
    return _make_parser().load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _normalise_needs(value: Any) -> list[str]:
    """Coerce a job's ``needs:`` value into a flat list of job names."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def test_every_external_action_is_pinned_to_full_lowercase_sha() -> None:
    """External actions must use immutable, lowercase commit identifiers."""
    invalid = [
        f"{name}: {reference}"
        for name, text in _workflow_texts().items()
        for reference in EXTERNAL_USE.findall(text)
        if PINNED_USE.fullmatch(reference) is None
    ]
    assert not invalid, "Unpinned external actions:\n" + "\n".join(invalid)


def test_workflows_do_not_force_a_javascript_runtime() -> None:
    """Actions must declare their supported runtime themselves."""
    combined = "\n".join(_workflow_texts().values())
    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" not in combined


def test_scheduled_advisory_workflows_exist() -> None:
    """Default-branch workflow files must include all scheduled advisories."""
    required = set(SCHEDULED_WORKFLOWS)
    assert required <= _workflow_texts().keys()


def test_release_drafter_omits_noisy_and_feature_branch_triggers() -> None:
    """Release drafting must ignore label churn and the retired feature branch."""
    release = _workflow_texts()["release-drafter.yml"]
    assert "labeled" not in release
    assert "unlabeled" not in release
    assert "deep-research" not in release
    assert "pull-requests: read" in release


def test_trusted_safety_job_has_fork_and_dependabot_condition() -> None:
    """Safety secrets must only be exposed to explicitly trusted changes."""
    ci_text = _workflow_texts()["ci.yml"]
    ci = _load_workflow("ci.yml")
    safety = ci["jobs"]["safety"]
    if_condition = str(safety.get("if", ""))
    assert "github.event_name != 'pull_request'" in if_condition
    assert "github.event.pull_request.head.repo.full_name == github.repository" in if_condition
    assert "github.actor == 'dependabot[bot]'" in if_condition
    assert "RUN_SAFETY_FOR_DEPENDABOT" not in if_condition
    recipe = " ".join(
        str(step.get("run", "")) for step in safety.get("steps") or [] if isinstance(step, dict)
    )
    assert "make safety-gate" in recipe
    assert "pull_request_target" not in ci_text


def test_scorecard_has_required_least_privileges() -> None:
    """Scorecard producer needs only source read, OIDC, and SARIF upload scopes."""
    scorecard = _load_workflow("scorecard.yml")
    producer = scorecard["jobs"]["scorecard"]
    permissions = producer.get("permissions") or {}
    assert permissions.get("contents") == "read"
    assert permissions.get("id-token") == "write"
    assert permissions.get("security-events") == "write"
    leaked = sorted(set(permissions) - {"contents", "id-token", "security-events"})
    assert not leaked, f"unexpected producer permissions: {leaked}"


def test_ci_has_concurrency_group() -> None:
    """CI workflow must declare a workflow-level concurrency group with cancel."""
    concurrency = _load_workflow("ci.yml").get("concurrency")
    assert isinstance(concurrency, dict), "ci.yml missing top-level 'concurrency' block"
    assert "group" in concurrency, "ci.yml concurrency block missing 'group'"
    assert "cancel-in-progress" in concurrency, (
        "ci.yml concurrency block missing 'cancel-in-progress'"
    )


def test_ci_jobs_have_timeouts() -> None:
    """Every CI job must declare a ``timeout-minutes`` ceiling."""
    jobs = _load_workflow("ci.yml")["jobs"]
    missing = [
        name for name, job in jobs.items() if isinstance(job, dict) and "timeout-minutes" not in job
    ]
    assert missing == [], f"ci.yml jobs missing 'timeout-minutes': {missing}"


def test_ci_has_no_needs_secret_scan() -> None:
    """The secret-scan job runs in parallel and must never gate another job."""
    jobs = _load_workflow("ci.yml")["jobs"]
    offenders = [
        name
        for name, job in jobs.items()
        if isinstance(job, dict) and "secret-scan" in _normalise_needs(job.get("needs"))
    ]
    assert offenders == [], f"ci.yml jobs declaring needs: secret-scan: {offenders}"


def test_scheduled_workflows_have_concurrency() -> None:
    """Every scheduled workflow must declare a concurrency group with cancel."""
    for name in SCHEDULED_WORKFLOWS:
        concurrency = _load_workflow(name).get("concurrency")
        assert isinstance(concurrency, dict), f"{name} missing 'concurrency' block"
        assert "group" in concurrency, f"{name} concurrency missing 'group'"
        assert "cancel-in-progress" in concurrency, (
            f"{name} concurrency missing 'cancel-in-progress'"
        )


def test_scheduled_workflows_have_timeouts() -> None:
    """Every job in a scheduled workflow must declare ``timeout-minutes``."""
    for name in SCHEDULED_WORKFLOWS:
        jobs = _load_workflow(name)["jobs"]
        missing = [
            job_name
            for job_name, job in jobs.items()
            if isinstance(job, dict) and "timeout-minutes" not in job
        ]
        assert missing == [], f"{name} jobs missing 'timeout-minutes': {missing}"


def test_no_continue_on_error_on_scheduled() -> None:
    """Scheduled mutation and Semgrep advisory jobs must not swallow failures."""
    for name in _NO_CONTINUE_ON_ERROR_WORKFLOWS:
        jobs = _load_workflow(name)["jobs"]
        offenders = [
            job_name
            for job_name, job in jobs.items()
            if isinstance(job, dict) and job.get("continue-on-error") is True
        ]
        assert offenders == [], f"{name} sets continue-on-error: true on: {offenders}"
