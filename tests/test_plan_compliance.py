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
    body = f"## Analyser Compliance Review\n{checklist}\n- Result: {result}\n"
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
    """A plan omitting a rule category is non-compliant."""
    partial = _FULL_CHECKLIST.replace(
        "- [PASS] typecheck-ty -- prevents type errors\n", ""
    ).replace("- [PASS] typecheck-pyright-strict -- prevents type errors\n", "")
    reasons = _validate(_plan(partial, "PASS"))
    assert any("type checking" in r for r in reasons)


def test_fail_marker_fails() -> None:
    """A category marked [FAIL] makes the plan non-compliant."""
    checklist = _FULL_CHECKLIST.replace(
        "[PASS] lint -- prevents lint violations",
        "[FAIL] lint -- prevents lint violations",
    )
    reasons = _validate(_plan(checklist, "PASS"))
    assert any("linting" in r and "FAIL" in r for r in reasons)


def test_missing_result_line_fails() -> None:
    """A compliance review without a Result line is non-compliant."""
    body = "## Analyser Compliance Review\n" + _FULL_CHECKLIST
    reasons = _validate(body)
    assert any("Result" in r for r in reasons)


def test_external_plan_requires_self_review() -> None:
    """An externally-produced plan must include a self-review section."""
    reasons = _validate(_plan(_FULL_CHECKLIST, "PASS", self_review=False))
    assert any("self-review" in r for r in reasons)
