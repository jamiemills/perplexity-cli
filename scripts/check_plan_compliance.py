"""Plan-compliance analyser (the post-plan gate).

Validates that a plan adheres to the prevention rules before a build
phase may consume it.

Usage::

    uv run python scripts/check_plan_compliance.py [--plan PATH]

Exit codes: 0 = compliant, 1 = non-compliant, 2 = no plan found.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLANS_DIR = PROJECT_ROOT / ".claude" / "plans"
DESCRIPTION = "Validate a produced plan against the prevention rules."

_REQUIRED_GATES = (
    "format-check",
    "lint",
    "typecheck-ty",
    "typecheck-pyright-strict",
    "bandit",
    "vulture",
    "complexity-cc",
    "complexity-mi",
    "semgrep-clean-code",
    "arch-check",
    "coupling-check",
    "file-size",
    "suppressions",
    "ruff-architecture",
    "pyright-strict",
    "semgrep-architecture",
    "deptry",
    "pip-audit",
    "test-coverage",
    "module-coverage",
)
_GATE_LINE = re.compile(r"^- \[(PASS|FAIL|SKIP)\] ([a-z0-9-]+)(?:\s|$)", re.IGNORECASE)
_SUMMARY_HEADING = re.compile(r"^## Summary$", re.MULTILINE)
_SUMMARY_HEADING_CASELESS = re.compile(r"^## summary$", re.IGNORECASE | re.MULTILINE)


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
    if path is not None:
        return path if path.is_file() else None
    if not PLANS_DIR.is_dir():
        return None
    candidates = sorted(PLANS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _extract_section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return ""
    body_start = text.find("\n", start) + 1
    next_section = text.find("\n## ", body_start)
    return text[body_start:next_section] if next_section >= 0 else text[body_start:]


def _gate_statuses(compliance: str) -> dict[str, list[str]]:
    statuses: dict[str, list[str]] = {}
    for line in compliance.splitlines():
        match = _GATE_LINE.match(line.strip())
        if match is None:
            continue
        status, gate = match.groups()
        status = status.upper()
        statuses.setdefault(gate, []).append(status)
    return statuses


def _result_line(compliance: str) -> str:
    for line in compliance.splitlines():
        stripped = line.strip().lower().lstrip("- ")
        if not stripped.startswith("result"):
            continue
        if "fail" in stripped:
            return "FAIL"
        if "pass" in stripped:
            return "PASS"
    return ""


def _gate_reasons(compliance: str) -> list[str]:
    statuses = _gate_statuses(compliance)
    reasons = [
        reason
        for gate in _REQUIRED_GATES
        if (reason := _required_gate_reason(gate, statuses.get(gate, []))) is not None
    ]
    required = set(_REQUIRED_GATES)
    unexpected = sorted(set(statuses) - required)
    reasons.extend(f"checklist contains unexpected gate: {gate}" for gate in unexpected)
    return reasons


def _required_gate_reason(gate: str, statuses: list[str]) -> str | None:
    if not statuses:
        return f"checklist missing gate: {gate}"
    if len(statuses) > 1:
        return f"checklist contains duplicate gate: {gate}"
    if statuses[0] != "PASS":
        return f"checklist gate marked {statuses[0]}: {gate}"
    return None


def _result_reasons(compliance: str) -> list[str]:
    result = _result_line(compliance)
    if not result:
        return ["missing 'Result: PASS|FAIL' line in the compliance review"]
    if result == "FAIL":
        return ["compliance review Result is FAIL"]
    return []


def _self_review_reasons(text: str) -> list[str]:
    heading_count = text.count("## Generated Plan Self-Review") + text.count("## Plan Self-Review")
    if heading_count != 1:
        return ["plan must contain exactly one self-review section"]
    review = _extract_section(text, "Generated Plan Self-Review")
    if not review:
        review = _extract_section(text, "Plan Self-Review")
    if not review:
        return ["missing self-review section"]
    result = _result_line(review)
    if result != "PASS":
        return ["self-review Result is not PASS"]
    return []


def _summary_reasons(text: str) -> list[str]:
    if len(_SUMMARY_HEADING_CASELESS.findall(text)) != 1:
        return ["plan must contain exactly one Summary section"]
    if len(_SUMMARY_HEADING.findall(text)) != 1:
        return ["plan must use the canonical '## Summary' heading"]
    summary = _extract_section(text, "Summary")
    results = [
        value.strip().upper()
        for line in summary.splitlines()
        if line.partition(":")[0].strip().lower().lstrip("- ") == "overall"
        for value in [line.partition(":")[2]]
    ]
    if len(results) != 1:
        return ["plan summary must contain exactly one Overall result"]
    if results[0] != "PASS":
        return ["plan summary Overall is not PASS"]
    return []


def _validate(text: str, require_self_review: bool = True) -> list[str]:
    if text.count("## Analyser Compliance Review") != 1:
        return ["plan must contain exactly one '## Analyser Compliance Review' section"]
    compliance = _extract_section(text, "Analyser Compliance Review")
    if not compliance:
        return ["missing '## Analyser Compliance Review' section"]
    reasons = _gate_reasons(compliance)
    reasons.extend(_result_reasons(compliance))
    if require_self_review:
        reasons.extend(_self_review_reasons(text))
    reasons.extend(_summary_reasons(text))
    return reasons


def _display(plan: Path) -> str:
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
        "\nA build phase must not consume this plan until it passes.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
