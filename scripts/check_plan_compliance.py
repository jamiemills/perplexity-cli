"""Plan-compliance analyser (the post-plan gate).

Validates that a plan -- the output of ``make quality-plan`` or any document
under ``.claude/plans/`` -- adheres to the prevention rules before a build
phase may consume it.  This is the "analyser run after a plan is produced"
required by ``.claude/analyzer-prevention-plan.md`` section 14.

It enforces the Analyzer Compliance Review contract: the plan must contain a
completed checklist covering every rule category (file-size, type boundaries,
complexity, layering, structural patterns, suppressions), each marked
``[PASS]``/``[FAIL]``, plus a consistent ``Result:`` line and a self-review
section.  A plan with any ``[FAIL]`` or a missing category is non-compliant.

Usage::

    uv run python scripts/check_plan_compliance.py [--plan PATH]

Exit codes: 0 = compliant, 1 = non-compliant, 2 = no plan found.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLANS_DIR = PROJECT_ROOT / ".claude" / "plans"
DESCRIPTION = "Validate a produced plan against the prevention rules."

# Each rule category and the synonyms that identify its checklist line.  The
# synonyms span both the generator's gate-name vocabulary and the
# quality-plan-reviewer subagent's rule-category vocabulary.
_REQUIRED_CATEGORIES = {
    "file size": ("file-size", "file size", "file sprawl"),
    "type boundaries (Any/unknown)": ("pyright-strict", "any boundary", "any/unknown", "unknown"),
    "complexity / parameters": ("ruff-architecture", "complexity", "parameter", "too-many"),
    "layering / imports": (
        "arch-check",
        "coupling",
        "import boundary",
        "layering",
        "layer boundary",
    ),
    "structural patterns (retry/status/TOCTOU)": (
        "semgrep-architecture",
        "retry",
        "toctou",
        "status",
        "structural",
    ),
    "suppressions": ("suppression",),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="Plan file to validate (default: newest .claude/plans/*.md).",
    )
    return parser.parse_args()


def _resolve_plan(path: Path | None) -> Path | None:
    """Return the explicit plan path or the newest plan under .claude/plans/."""
    if path is not None:
        return path if path.is_file() else None
    if not PLANS_DIR.is_dir():
        return None
    candidates = sorted(PLANS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _extract_section(text: str, heading: str) -> str:
    """Return the body of a ``## <heading>`` section (up to the next ``## ``)."""
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return ""
    body_start = text.find("\n", start) + 1
    next_section = text.find("\n## ", body_start)
    return text[body_start:next_section] if next_section >= 0 else text[body_start:]


def _matches_synonym(line_lower: str, synonyms: tuple[str, ...]) -> bool:
    """True if any synonym appears in the lower-cased line."""
    return any(syn in line_lower for syn in synonyms)


def _line_marker(line_lower: str) -> str | None:
    """Return 'pass'/'fail' for a ``[PASS]``/``[FAIL]`` line, else None."""
    if "[fail]" in line_lower:
        return "fail"
    if "[pass]" in line_lower:
        return "pass"
    return None


def _category_status(compliance: str, synonyms: tuple[str, ...]) -> str:
    """Return 'pass', 'fail', or 'missing' for one rule category."""
    for line in compliance.splitlines():
        lower = line.lower()
        if _matches_synonym(lower, synonyms):
            marker = _line_marker(lower)
            if marker:
                return marker
    return "missing"


def _result_line(compliance: str) -> str:
    """Return the overall Result value from the compliance section, or '' ."""
    for line in compliance.splitlines():
        stripped = line.strip().lower().lstrip("- ")
        if not stripped.startswith("result"):
            continue
        if "fail" in stripped:
            return "FAIL"
        if "pass" in stripped:
            return "PASS"
    return ""


def _has_self_review(text: str) -> bool:
    """True if the plan contains a self-review section."""
    return bool(
        _extract_section(text, "Generated Plan Self-Review")
        or _extract_section(text, "Plan Self-Review")
    )


def _category_reasons(compliance: str) -> list[str]:
    """Collect missing/failed checklist categories."""
    reasons: list[str] = []
    for category, synonyms in _REQUIRED_CATEGORIES.items():
        status = _category_status(compliance, synonyms)
        if status == "missing":
            reasons.append(f"checklist missing category: {category}")
        elif status == "fail":
            reasons.append(f"checklist category marked FAIL: {category}")
    return reasons


def _result_reasons(compliance: str) -> list[str]:
    """Return reasons for a missing or failing Result line."""
    result = _result_line(compliance)
    if not result:
        return ["missing 'Result: PASS|FAIL' line in the compliance review"]
    if result == "FAIL":
        return ["compliance review Result is FAIL"]
    return []


def _validate(text: str, require_self_review: bool = True) -> list[str]:
    """Validate plan text; return a list of failure reasons (empty = compliant).

    ``require_self_review`` is False when the generator calls this on a body
    that has not yet had its self-review section appended.
    """
    compliance = _extract_section(text, "Analyzer Compliance Review")
    if not compliance:
        return ["missing '## Analyzer Compliance Review' section"]

    reasons = _category_reasons(compliance)
    reasons.extend(_result_reasons(compliance))
    if require_self_review and not _has_self_review(text):
        reasons.append("missing self-review section")
    return reasons


def _display(plan: Path) -> str:
    """Return a readable path, relative to the project root when possible."""
    try:
        return str(plan.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(plan)


def main() -> None:
    args = _parse_args()
    plan = _resolve_plan(args.plan)
    if plan is None:
        print(
            "No plan found to validate (pass --plan PATH or generate one via `make quality-plan`).",
            file=sys.stderr,
        )
        sys.exit(2)

    reasons = _validate(plan.read_text(encoding="utf-8"))
    if not reasons:
        print(f"Plan compliance PASSED: {_display(plan)} adheres to the prevention rules.")
        return

    print(f"Plan compliance FAILED: {_display(plan)}\n", file=sys.stderr)
    for reason in reasons:
        print(f"  - {reason}", file=sys.stderr)
    print(
        "\nA build phase must not consume this plan until it passes. Update the "
        "plan's Analyzer Compliance Review or re-run the quality-plan-reviewer subagent.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
