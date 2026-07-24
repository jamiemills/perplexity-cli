"""Plan-compliance analyser tests.

Exercises the post-plan gate (scripts/check_plan_compliance.py) that validates a
produced plan against the prevention rules before a build phase consumes it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_plan_compliance import _validate  # type: ignore[import-not-found]


def _plan(checklist: str, result: str, *, self_review: bool = True) -> str:
    """Assemble a minimal plan body for validation."""
    body = (
        f"## Summary\n- Overall: {result}\n\n"
        f"## Analyser Compliance Review\n{checklist}\n- Result: {result}\n"
    )
    if self_review:
        body += "\n## Generated Plan Self-Review\n- Result: PASS\n"
    return body


_FULL_CHECKLIST = """\
- [PASS] format-check -- prevents code style
- [PASS] lint -- prevents lint violations
- [PASS] typecheck-ty -- prevents type errors
- [PASS] typecheck-pyright-strict -- prevents type errors
- [PASS] bandit -- prevents security
- [PASS] vulture -- prevents dead code
- [PASS] complexity-cc -- prevents complexity
- [PASS] complexity-mi -- prevents maintainability
- [PASS] semgrep-clean-code -- prevents clean-code violations
- [PASS] arch-check -- prevents layer-boundary violations
- [PASS] coupling-check -- prevents coupling
- [PASS] file-size -- prevents file sprawl
- [PASS] suppressions -- prevents suppression creep
- [PASS] ruff-architecture -- prevents complexity/params
- [PASS] pyright-strict -- prevents type boundaries
- [PASS] semgrep-architecture -- prevents structural patterns
- [PASS] deptry -- prevents missing deps
- [PASS] pip-audit -- prevents known vulns
- [PASS] test-coverage -- prevents insufficient coverage
- [PASS] module-coverage -- prevents per-module gaps
"""


def test_compliant_plan_passes() -> None:
    """A complete, all-PASS plan has no validation reasons."""
    reasons = _validate(_plan(_FULL_CHECKLIST, "PASS"))
    assert reasons == [], "Expected compliant plan, got reasons:\n  " + "\n  ".join(reasons)


def test_missing_category_fails() -> None:
    """A plan omitting even one named gate is non-compliant."""
    partial = _FULL_CHECKLIST.replace("- [PASS] typecheck-ty -- prevents type errors\n", "")
    reasons = _validate(_plan(partial, "PASS"))
    assert "checklist missing gate: typecheck-ty" in reasons


def test_fail_marker_fails() -> None:
    """A category marked [FAIL] makes the plan non-compliant."""
    checklist = _FULL_CHECKLIST.replace(
        "[PASS] lint -- prevents lint violations",
        "[FAIL] lint -- prevents lint violations",
    )
    reasons = _validate(_plan(checklist, "PASS"))
    assert "checklist gate marked FAIL: lint" in reasons


def test_missing_result_line_fails() -> None:
    """A compliance review without a Result line is non-compliant."""
    body = "## Summary\n- Overall: PASS\n\n## Analyser Compliance Review\n" + _FULL_CHECKLIST
    reasons = _validate(body)
    assert any("Result" in r for r in reasons)


def test_external_plan_requires_self_review() -> None:
    """An externally-produced plan must include a self-review section."""
    reasons = _validate(_plan(_FULL_CHECKLIST, "PASS", self_review=False))
    assert any("self-review" in r for r in reasons)


def test_skipped_gate_fails() -> None:
    """A skipped blocking gate cannot produce a compliant plan."""
    checklist = _FULL_CHECKLIST.replace("[PASS] semgrep-clean-code", "[SKIP] semgrep-clean-code")
    reasons = _validate(_plan(checklist, "PASS"))
    assert "checklist gate marked SKIP: semgrep-clean-code" in reasons


def test_failing_self_review_fails() -> None:
    """The self-review must contain an explicit passing result."""
    plan = _plan(_FULL_CHECKLIST, "PASS").replace(
        "## Generated Plan Self-Review\n- Result: PASS",
        "## Generated Plan Self-Review\n- Result: FAIL",
    )
    reasons = _validate(plan)
    assert "self-review Result is not PASS" in reasons


def test_unexpected_skipped_gate_fails() -> None:
    """An extra skipped gate cannot be used to claim complete compliance."""
    checklist = _FULL_CHECKLIST + "- [skip] safety-gate -- authenticated scan\n"
    reasons = _validate(_plan(checklist, "PASS"))
    assert "checklist contains unexpected gate: safety-gate" in reasons


def test_case_insensitive_failing_summary_fails() -> None:
    """Summary results are parsed structurally and case-insensitively."""
    plan = _plan(_FULL_CHECKLIST, "PASS").replace("- Overall: PASS", "- Overall: fail")
    reasons = _validate(plan)
    assert "plan summary Overall is not PASS" in reasons


def test_noncanonical_or_duplicate_summary_fails() -> None:
    """Summary headings cannot hide a later contradictory result."""
    lowercase = _plan(_FULL_CHECKLIST, "PASS").replace("## Summary", "## summary")
    duplicate = _plan(_FULL_CHECKLIST, "PASS") + "\n## Summary\n- Overall: FAIL\n"

    assert "plan must use the canonical '## Summary' heading" in _validate(lowercase)
    assert "plan must contain exactly one Summary section" in _validate(duplicate)
