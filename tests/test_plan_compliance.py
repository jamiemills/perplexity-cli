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
    body = f"## Analyzer Compliance Review\n{checklist}\n- Result: {result}\n"
    if self_review:
        body += "\n## Generated Plan Self-Review\n- Result: PASS\n"
    return body


_FULL_CHECKLIST = """\
- [PASS] file-size impact checked
- [PASS] new Any/unknown boundaries avoided
- [PASS] complexity / parameter limits checked
- [PASS] import boundary impact checked
- [PASS] retry/error-classification ownership checked
- [PASS] no new hand-written schema duplication
- [PASS] no new suppressions without ticket
- [PASS] canonical-home / layering rules checked
"""


def test_compliant_plan_passes() -> None:
    """A complete, all-PASS plan has no validation reasons."""
    reasons = _validate(_plan(_FULL_CHECKLIST, "PASS"))
    assert reasons == [], "Expected compliant plan, got reasons:\n  " + "\n  ".join(reasons)


def test_missing_category_fails() -> None:
    """A plan omitting a rule category is non-compliant."""
    partial = _FULL_CHECKLIST.replace("- [PASS] new Any/unknown boundaries avoided\n", "")
    reasons = _validate(_plan(partial, "PASS"))
    assert any("type boundaries" in r for r in reasons)


def test_fail_marker_fails() -> None:
    """A category marked [FAIL] makes the plan non-compliant."""
    checklist = _FULL_CHECKLIST.replace(
        "[PASS] no new suppressions without ticket",
        "[FAIL] no new suppressions without ticket",
    )
    reasons = _validate(_plan(checklist, "PASS"))
    assert any("suppressions" in r and "FAIL" in r for r in reasons)


def test_missing_result_line_fails() -> None:
    """A compliance review without a Result line is non-compliant."""
    body = "## Analyzer Compliance Review\n" + _FULL_CHECKLIST
    reasons = _validate(body)
    assert any("Result" in r for r in reasons)


def test_external_plan_requires_self_review() -> None:
    """An externally-produced plan must include a self-review section."""
    reasons = _validate(_plan(_FULL_CHECKLIST, "PASS", self_review=False))
    assert any("self-review" in r for r in reasons)
