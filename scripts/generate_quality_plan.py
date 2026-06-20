"""Comprehensive quality-plan generator.

Runs every quality ratchet and analyser in one pass, compares each against its
tracked baseline, and writes a deterministic Markdown plan artefact that a
later build phase can consume.  The plan distinguishes baselined debt from new
regressions and includes the ``Analyzer Compliance Review`` and ``Generated
Plan Self-Review`` checklists required by ``.claude/analyzer-prevention-plan.md``
section 13.

The generator does not modify source or baselines.  By default it writes the
plan even when findings exist; pass ``--fail-on-violations`` to exit non-zero
when any gate reports a regression.

Usage::

    uv run python scripts/generate_quality_plan.py [--out PATH] [--fail-on-violations]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
DEFAULT_OUT = PROJECT_ROOT / ".claude" / "plans" / "quality-plan.md"

sys.path.insert(0, str(SCRIPTS))
from check_plan_compliance import _validate  # noqa: E402  (sys.path must be set first)

DESCRIPTION = "Run all quality analysers and write a follow-up plan artefact."


@dataclass(frozen=True, slots=True)
class Gate:
    """A single analyser invocation."""

    name: str
    command: tuple[str, ...]
    prevents: str


@dataclass
class GateResult:
    """Outcome of running one gate."""

    name: str
    prevents: str
    passed: bool
    output: str = ""


_GATES: tuple[Gate, ...] = (
    Gate("file-size", ("uv", "run", "python", "scripts/check_file_size.py"), "§1a file sprawl"),
    Gate(
        "suppressions",
        ("uv", "run", "python", "scripts/check_suppressions.py"),
        "hidden-suppression creep",
    ),
    Gate(
        "ruff-architecture",
        ("uv", "run", "python", "scripts/check_ruff_architecture.py"),
        "§5 complexity/params",
    ),
    Gate(
        "pyright-strict",
        ("uv", "run", "python", "scripts/check_pyright_strict.py"),
        "§3 Any boundaries",
    ),
    Gate(
        "semgrep-architecture",
        ("uv", "run", "python", "scripts/check_semgrep_architecture.py"),
        "§2a/2c/4/6 patterns",
    ),
    Gate(
        "arch-check",
        ("uv", "run", "python", "scripts/check_architecture.py"),
        "§6 layer boundaries",
    ),
    Gate("coupling-check", ("uv", "run", "python", "scripts/check_coupling.py"), "§4/§6 coupling"),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Destination Markdown plan.")
    parser.add_argument(
        "--fail-on-violations",
        action="store_true",
        help="Exit non-zero when any gate reports a regression.",
    )
    parser.add_argument(
        "--validate-plan",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the plan-compliance analyser on the generated plan (default: enabled).",
    )
    return parser.parse_args()


def _run_gate(gate: Gate) -> GateResult:
    """Run one gate and capture its pass/fail status and output."""
    result = subprocess.run(
        gate.command, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=300
    )
    output = (result.stdout + result.stderr).strip()
    return GateResult(gate.name, gate.prevents, result.returncode == 0, output)


def _compliance_lines(results: list[GateResult]) -> list[str]:
    """Build the Analyzer Compliance Review checklist."""
    lines = ["## Analyzer Compliance Review"]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"- [{status}] {result.name} — prevents {result.prevents}")
    overall = "PASS" if all(r.passed for r in results) else "FAIL"
    lines.append(f"- Result: {overall}")
    return lines


def _findings_section(results: list[GateResult]) -> list[str]:
    """Build the per-gate findings section (failures get full output)."""
    lines = ["## Findings By Analyzer"]
    for result in results:
        if result.passed:
            summary = result.output.splitlines()[0] if result.output else "passed"
            lines.append(f"### {result.name}: PASS\n\n{summary}\n")
        else:
            lines.append(f"### {result.name}: FAIL\n\n```\n{result.output}\n```\n")
    return lines


def _work_items(results: list[GateResult]) -> list[str]:
    """Propose one build-phase work item per failing gate."""
    lines = ["## Proposed Build-Phase Work Items"]
    failing = [r for r in results if not r.passed]
    if not failing:
        lines.append("No new regressions — no build-phase work required.")
        return lines
    for index, result in enumerate(failing, start=1):
        lines.append(f"{index}. Resolve `{result.name}` regressions (prevents {result.prevents}).")
    return lines


def _self_review(reasons: list[str]) -> list[str]:
    """Build the self-review section from the plan-compliance analyser result."""
    status = "PASS" if not reasons else "FAIL"
    lines = [
        "## Generated Plan Self-Review",
        "- post-plan analyser: scripts/check_plan_compliance.py",
        f"- categories covered and internally consistent: {status}",
    ]
    if reasons:
        lines.append("Failures:")
        lines.extend(f"  - {reason}" for reason in reasons)
    lines.append(f"- Result: {status}")
    lines.append(
        "\nA later build phase must not consume this plan unless both "
        "`Analyzer Compliance Review` and `Generated Plan Self-Review` are PASS."
    )
    return lines


def _build_plan(results: list[GateResult], validate: bool) -> tuple[str, list[str]]:
    """Assemble the Markdown plan and return ``(plan_text, self_review_reasons)``."""
    regressions = sum(1 for r in results if not r.passed)
    overall = "PASS" if regressions == 0 else "FAIL"
    header = dedent(f"""\
        # Generated Quality Plan

        > Prevention-only artefact produced by `make quality-plan`.
        > Existing debt is baselined; only NEW regressions require action.

        ## Summary
        - Gates run: {len(results)}
        - New regressions: {regressions}
        - Overall: {overall}
    """)
    body = [
        header,
        "\n".join(_compliance_lines(results)),
        "\n".join(_findings_section(results)),
        "\n".join(_work_items(results)),
    ]
    body_text = "\n\n".join(body) + "\n"
    reasons = _validate(body_text, require_self_review=False) if validate else []
    return body_text + "\n\n" + "\n".join(_self_review(reasons)) + "\n", reasons


def _write_plan(plan: str, out: Path, regression_count: int) -> None:
    """Persist the plan artefact."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(plan, encoding="utf-8")
    print(f"Quality plan written: {out} ({regression_count} regression(s)).")


def _emit_reasons(reasons: list[str]) -> None:
    """Print self-review failures to stderr."""
    if not reasons:
        return
    print("Plan self-review FAILED:", file=sys.stderr)
    for reason in reasons:
        print(f"  - {reason}", file=sys.stderr)


def _exit_code(
    regression_count: int, reasons: list[str], fail_on_violations: bool, validate_plan: bool
) -> int:
    """Decide the process exit code from gate and self-review outcomes."""
    if validate_plan and reasons:
        return 1
    if regression_count and fail_on_violations:
        return 1
    return 0


def main() -> None:
    args = _parse_args()
    results = [_run_gate(gate) for gate in _GATES]
    plan_text, reasons = _build_plan(results, args.validate_plan)
    regression_count = sum(1 for r in results if not r.passed)
    _write_plan(plan_text, args.out, regression_count)
    _emit_reasons(reasons)
    sys.exit(_exit_code(regression_count, reasons, args.fail_on_violations, args.validate_plan))


if __name__ == "__main__":
    main()
