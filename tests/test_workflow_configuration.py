"""Static policy tests for GitHub workflow configuration."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
EXTERNAL_USE = re.compile(r"^\s*uses:\s*(?!\./)(\S+)", re.MULTILINE)
PINNED_USE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _workflow_texts() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.y*ml"))
    }


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
    required = {"mutation-scheduled.yml", "scorecard.yml", "semgrep-advisory.yml"}
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
    ci = _workflow_texts()["ci.yml"]
    safety = ci[ci.index("  safety:") : ci.index("  test-macos:")]
    assert "github.event_name != 'pull_request'" in safety
    assert "github.event.pull_request.head.repo.full_name == github.repository" in safety
    assert "github.actor == 'dependabot[bot]'" in safety
    assert "RUN_SAFETY_FOR_DEPENDABOT" not in safety
    assert "make safety-gate" in safety
    assert "pull_request_target" not in ci


def test_scorecard_has_required_least_privileges() -> None:
    """Scorecard needs only source read, OIDC, and SARIF upload permissions."""
    scorecard = _workflow_texts()["scorecard.yml"]
    assert "contents: read" in scorecard
    assert "id-token: write" in scorecard
    assert "security-events: write" in scorecard
