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


def test_trusted_safety_job_runs_only_on_push() -> None:
    """Safety secrets must only be exposed on trusted push events."""
    ci_text = _workflow_texts()["ci.yml"]
    ci = _load_workflow("ci.yml")
    safety = ci["jobs"]["safety"]
    if_condition = str(safety.get("if", ""))
    assert "github.event_name == 'push'" in if_condition
    assert "RUN_SAFETY_FOR_DEPENDABOT" not in if_condition
    recipe = " ".join(
        str(step.get("run", "")) for step in safety.get("steps") or [] if isinstance(step, dict)
    )
    assert "make safety-gate" in recipe
    assert "pull_request_target" not in ci_text


def test_pip_audit_job_is_credential_free() -> None:
    """PR CI must include a credential-free dependency audit."""
    ci = _load_workflow("ci.yml")
    pip_audit = ci["jobs"]["pip-audit"]
    assert "timeout-minutes" in pip_audit
    recipe = " ".join(
        str(step.get("run", "")) for step in pip_audit.get("steps") or [] if isinstance(step, dict)
    )
    assert "make pip-audit" in recipe
    for step in pip_audit.get("steps") or []:
        if isinstance(step, dict):
            assert "env" not in step, f"pip-audit step must not use secrets: {step.get('name')}"


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
    group = str(concurrency["group"])
    assert "github.run_id" in group, "manual dispatches need unique concurrency groups"


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


def test_ci_has_hermetic_integration_job() -> None:
    """CI must run the hermetic integration lane under the default-on guard."""
    ci = _load_workflow("ci.yml")
    job = ci["jobs"]["hermetic-integration"]
    assert job["runs-on"] == "ubuntu-latest"
    recipe = " ".join(str(step.get("run", "")) for step in job["steps"] if isinstance(step, dict))
    assert "make test-integration" in recipe
    assert "RUN_REAL_API_TESTS" not in recipe
    assert "permissions" not in job or job["permissions"]["contents"] == "read"


def test_ci_has_windows_packaging_smoke_job() -> None:
    """CI must smoke the wheel on Windows with bounded, network-free commands."""
    ci = _load_workflow("ci.yml")
    job = ci["jobs"]["windows_packaging_smoke"]
    assert job["runs-on"] == "windows-latest"
    assert _normalise_needs(job.get("needs")) == ["package"]
    uses = [
        str(step.get("uses", ""))
        for step in job["steps"]
        if isinstance(step, dict) and step.get("uses")
    ]
    assert any("download-artifact" in use for use in uses)
    recipe = " ".join(str(step.get("run", "")) for step in job["steps"] if isinstance(step, dict))
    for command in (
        "pxcli.exe --version",
        "pxcli.exe config show",
        "pxcli.exe skill show",
        "perplexity-cli.exe --version",
        "pxcli-mcp.exe --help",
    ):
        assert command in recipe


def test_ci_test_coverage_installs_gitleaks() -> None:
    """The coverage job must install gitleaks before running the suite."""
    ci = _load_workflow("ci.yml")
    steps = ci["jobs"]["test-coverage"]["steps"]
    names = [step.get("name", "") for step in steps]
    assert "Install gitleaks 8.30.1" in names
    gitleaks_step = next(step for step in steps if step.get("name") == "Install gitleaks 8.30.1")
    assert "8.30.1" in str(gitleaks_step.get("run", ""))
    run_index = names.index("Run tests with coverage")
    install_index = names.index("Install gitleaks 8.30.1")
    assert install_index < run_index


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


def test_mutation_workflow_runs_full_policy() -> None:
    """Scheduled mutation must retain the full policy wrapper command."""
    mutation = _workflow_texts()["mutation-scheduled.yml"]
    assert "run: make mutate-full-policy" in mutation


def test_mutation_workflow_uses_generated_report_path() -> None:
    """Every scheduled report reader and upload must use generated evidence."""
    mutation = _workflow_texts()["mutation-scheduled.yml"]
    assert mutation.count("build/reports/mutation-report.json") == 3
    assert "quality/evidence/mutation-report.json" not in mutation


def test_mutation_summary_and_report_upload_always_run() -> None:
    """Mutation findings and tool errors must still publish available evidence."""
    mutation = _load_workflow("mutation-scheduled.yml")
    steps = mutation["jobs"]["mutation"]["steps"]
    named_steps = {step["name"]: step for step in steps}
    assert named_steps["Job summary"]["if"] == "always()"
    assert named_steps["Upload mutation report"]["if"] == "always()"
    assert (
        named_steps["Upload mutation report"]["with"]["path"]
        == "build/reports/mutation-report.json"
    )


def test_mutation_workflow_uploads_mutmut3_metadata() -> None:
    """Scheduled mutation evidence must use mutmut 3's actual metadata path."""
    mutation = _load_workflow("mutation-scheduled.yml")
    steps = mutation["jobs"]["mutation"]["steps"]
    metadata = next(step for step in steps if step.get("name") == "Upload mutmut metadata")
    assert metadata["if"] == "always()"
    assert metadata["with"]["path"] == "mutants/"
    assert ".mutmut-cache" not in _workflow_texts()["mutation-scheduled.yml"]
