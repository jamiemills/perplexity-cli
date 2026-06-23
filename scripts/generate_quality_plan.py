"""Comprehensive quality-plan generator.

Runs every quality analyser in one pass, compares each against its
tracked baseline (where applicable), and writes a deterministic Markdown
plan artefact that a later build phase can consume.  The plan distinguishes
baselined debt from new regressions and includes the ``Analyser Compliance
Review`` and ``Generated Plan Self-Review`` checklists required by
``.claude/analyzer-prevention-plan.md`` section 13.

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
from _gates import load_gates  # noqa: E402
from check_plan_compliance import _validate  # noqa: E402

_gates = load_gates()

DESCRIPTION = "Run all quality analysers and write a follow-up plan artefact."


@dataclass(frozen=True, slots=True)
class Gate:
    """A single analyser invocation."""

    name: str
    command: tuple[str, ...]
    prevents: str
    category: str = ""


@dataclass
class GateResult:
    """Outcome of running one gate."""

    name: str
    prevents: str
    category: str
    passed: bool
    skipped: bool = False
    output: str = ""


def _build_format_gates() -> tuple[Gate, ...]:
    return (
        Gate(
            "format-check",
            ("uv", "run", "ruff", "format", "--check", "src", "tests"),
            "code style divergence",
            "formatting",
        ),
    )


def _build_lint_gates() -> tuple[Gate, ...]:
    return (
        Gate(
            "lint",
            ("uv", "run", "ruff", "check", "src", "tests"),
            "lint violations",
            "linting",
        ),
    )


def _build_typecheck_gates() -> tuple[Gate, ...]:
    return (
        Gate(
            "typecheck-ty",
            ("uv", "run", "ty", "check", "src"),
            "type errors (ty)",
            "typing",
        ),
        Gate(
            "typecheck-pyright-strict",
            ("uv", "run", "pyright", "src/"),
            "type errors (pyright strict)",
            "typing",
        ),
    )


def _build_security_gates() -> tuple[Gate, ...]:
    return (
        Gate(
            "bandit",
            ("uv", "run", "bandit", "-c", "pyproject.toml", "-r", "src/"),
            "security vulnerabilities",
            "security",
        ),
        Gate(
            "vulture",
            (
                "uv",
                "run",
                "vulture",
                "src/",
                "vulture_whitelist.py",
                "--min-confidence",
                str(_gates["MIN_CONFIDENCE"]),
            ),
            "dead code accumulation",
            "security",
        ),
    )


def _build_complexity_gates() -> tuple[Gate, ...]:
    return (
        Gate(
            "complexity-cc",
            ("uv", "run", "radon", "cc", "src/", "-s", "-n", _gates["RADON_CC_GRADE"]),
            "cyclomatic-complexity violations",
            "complexity",
        ),
        Gate(
            "complexity-mi",
            ("uv", "run", "radon", "mi", "src/", "-s", "-n", _gates["RADON_MI_GRADE"]),
            "maintainability-index violations",
            "complexity",
        ),
    )


def _build_semgrep_gates() -> tuple[Gate, ...]:
    return (
        Gate(
            "semgrep-clean-code",
            (
                "uvx",
                "semgrep",
                "--config",
                ".semgrep.yml",
                "--config",
                "p/python",
                "--config",
                "p/comment",
                "--config",
                "p/r2c-best-practices",
                "--severity",
                "ERROR",
                "--severity",
                "WARNING",
                "--exclude-rule",
                "python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure",
                "--exclude",
                "tests/",
                "--error",
                "--metrics=off",
                ".",
            ),
            "clean-code rule violations",
            "semgrep",
        ),
    )


def _build_architecture_gates() -> tuple[Gate, ...]:
    return (
        Gate(
            "arch-check",
            ("uv", "run", "python", "scripts/check_architecture.py", "--no-baseline"),
            "layer-boundary violations",
            "architecture",
        ),
        Gate(
            "coupling-check",
            (
                "uv",
                "run",
                "python",
                "scripts/check_coupling.py",
                "--max-flagged",
                str(_gates["MAX_FLAGGED"]),
            ),
            "coupling/sprawl violations",
            "architecture",
        ),
    )


def _build_ratchet_gates() -> tuple[Gate, ...]:
    return (
        Gate(
            "file-size",
            (
                "uv",
                "run",
                "python",
                "scripts/check_file_size.py",
                "--max-lines",
                str(_gates["FILE_SIZE_CAP"]),
            ),
            "file-size sprawl",
            "ratchets",
        ),
        Gate(
            "suppressions",
            ("uv", "run", "python", "scripts/check_suppressions.py"),
            "suppression creep",
            "ratchets",
        ),
        Gate(
            "ruff-architecture",
            ("uv", "run", "python", "scripts/check_ruff_architecture.py"),
            "complexity/parameter violations",
            "ratchets",
        ),
        Gate(
            "pyright-strict",
            ("uv", "run", "python", "scripts/check_pyright_strict.py"),
            "Any/unknown type boundaries",
            "ratchets",
        ),
        Gate(
            "semgrep-architecture",
            ("uv", "run", "python", "scripts/check_semgrep_architecture.py"),
            "structural pattern violations",
            "ratchets",
        ),
    )


def _build_dependency_gates() -> tuple[Gate, ...]:
    return (
        Gate(
            "deptry",
            ("uv", "run", "deptry", "src", "tests", "scripts"),
            "missing/unused/misplaced dependencies",
            "dependencies",
        ),
        Gate(
            "pip-audit",
            ("uv", "run", "pip-audit", "."),
            "known dependency vulnerabilities",
            "dependencies",
        ),
    )


def _build_coverage_gates() -> tuple[Gate, ...]:
    return (
        Gate(
            "test-coverage",
            (
                "uv",
                "run",
                "pytest",
                "tests/",
                "-q",
                "--tb=line",
                "-x",
                "-n",
                "auto",
                "--cov=perplexity_cli",
                "--cov-report=term",
                "--cov-report=json",
                "--cov-report=xml:coverage.xml",
            ),
            "insufficient test coverage",
            "coverage",
        ),
        Gate(
            "module-coverage",
            (
                "uv",
                "run",
                "python",
                "scripts/check_module_coverage.py",
                "--min-coverage",
                str(_gates["MIN_COVERAGE"]),
            ),
            "per-module coverage below threshold",
            "coverage",
        ),
    )


_GATES: tuple[Gate, ...] = (
    *_build_format_gates(),
    *_build_lint_gates(),
    *_build_typecheck_gates(),
    *_build_security_gates(),
    *_build_complexity_gates(),
    *_build_semgrep_gates(),
    *_build_architecture_gates(),
    *_build_ratchet_gates(),
    *_build_dependency_gates(),
    *_build_coverage_gates(),
)

_GATE_CATEGORIES = (
    ("formatting", "Formatting"),
    ("linting", "Linting"),
    ("typing", "Type Checking"),
    ("security", "Security & Dead Code"),
    ("complexity", "Complexity"),
    ("semgrep", "Semgrep Static Analysis"),
    ("architecture", "Architecture"),
    ("ratchets", "Quality Ratchets & Hard Gates"),
    ("dependencies", "Dependency Hygiene"),
    ("coverage", "Test Coverage"),
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
        help="Run the plan-compliance analyser on the generated plan.",
    )
    parser.add_argument(
        "--skip-coverage",
        action="store_true",
        help="Skip the slow test-coverage gates.",
    )
    parser.add_argument(
        "--skip-semgrep",
        action="store_true",
        help="Skip the slow semgrep gates.",
    )
    return parser.parse_args()


def _run_gate(gate: Gate) -> GateResult:
    """Run one gate and capture its pass/fail status and output."""
    result = subprocess.run(
        gate.command, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=600
    )
    output = (result.stdout + result.stderr).strip()
    return GateResult(
        gate.name, gate.prevents, gate.category, result.returncode == 0, False, output
    )


def _skipped_result(gate: Gate) -> GateResult:
    """Return a skipped result for a gate that was not run."""
    return GateResult(gate.name, gate.prevents, gate.category, True, True, "(skipped)")


def _compliance_lines(results: list[GateResult]) -> list[str]:
    """Build the Analyser Compliance Review checklist, grouped by category."""
    lines = ["## Analyser Compliance Review"]
    for _cat_key, cat_label in _GATE_CATEGORIES:
        cat_results = [r for r in results if r.category == _cat_key]
        if not cat_results:
            continue
        lines.append(f"\n### {cat_label}")
        for result in cat_results:
            if result.skipped:
                status = "SKIP"
            else:
                status = "PASS" if result.passed else "FAIL"
            lines.append(f"- [{status}] {result.name} -- prevents {result.prevents}")
    run_results = [r for r in results if not r.skipped]
    overall = "PASS" if all(r.passed for r in run_results) else "FAIL"
    lines.append(f"\n- Result: {overall}")
    return lines


def _findings_section(results: list[GateResult]) -> list[str]:
    """Build the per-gate findings section, grouped by category."""
    lines = ["## Findings By Analyser"]
    for _cat_key, cat_label in _GATE_CATEGORIES:
        cat_results = [r for r in results if r.category == _cat_key]
        if not cat_results:
            continue
        lines.append(f"\n### {cat_label}")
        for result in cat_results:
            if result.skipped:
                lines.append(f"#### {result.name}: SKIPPED\n\n{result.output}\n")
            elif result.passed:
                summary = result.output.splitlines()[0] if result.output else "passed"
                lines.append(f"#### {result.name}: PASS\n\n{summary}\n")
            else:
                lines.append(f"#### {result.name}: FAIL\n\n```\n{result.output}\n```\n")
    return lines


def _work_items(results: list[GateResult]) -> list[str]:
    """Propose one build-phase work item per failing gate."""
    lines = ["## Proposed Build-Phase Work Items"]
    failing = [r for r in results if not r.passed and not r.skipped]
    if not failing:
        lines.append("No new regressions -- no build-phase work required.")
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
        "`Analyser Compliance Review` and `Generated Plan Self-Review` are PASS."
    )
    return lines


def _build_plan(results: list[GateResult], validate: bool) -> tuple[str, list[str]]:
    """Assemble the Markdown plan and return ``(plan_text, self_review_reasons)``."""
    run_results = [r for r in results if not r.skipped]
    regressions = sum(1 for r in run_results if not r.passed)
    overall = "PASS" if regressions == 0 else "FAIL"
    header = dedent(f"""\
        # Generated Quality Plan

        > Prevention-only artefact produced by `make quality-plan`.
        > Existing debt is baselined; only NEW regressions require action.

        ## Summary
        - Gates run: {len(run_results)}
        - Gates skipped: {sum(1 for r in results if r.skipped)}
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
    regression_count: int,
    reasons: list[str],
    fail_on_violations: bool,
    validate_plan: bool,
) -> int:
    """Decide the process exit code from gate and self-review outcomes."""
    if validate_plan and reasons:
        return 1
    if regression_count and fail_on_violations:
        return 1
    return 0


def main() -> None:
    args = _parse_args()
    gates: list[Gate] = []
    for gate in _GATES:
        if args.skip_coverage and gate.category == "coverage":
            continue
        if args.skip_semgrep and gate.category == "semgrep":
            continue
        gates.append(gate)

    results = [_run_gate(gate) for gate in gates]

    if args.skip_coverage:
        skipped_coverage = [g for g in _GATES if g.category == "coverage"]
        results.extend(_skipped_result(g) for g in skipped_coverage)
    if args.skip_semgrep:
        skipped_semgrep = [g for g in _GATES if g.category == "semgrep"]
        results.extend(_skipped_result(g) for g in skipped_semgrep)

    results.sort(
        key=lambda r: (
            [k for k, _ in _GATE_CATEGORIES].index(r.category)
            if r.category in [k for k, _ in _GATE_CATEGORIES]
            else 99
        )
    )

    plan_text, reasons = _build_plan(results, args.validate_plan)
    regression_count = sum(1 for r in results if not r.passed and not r.skipped)
    _write_plan(plan_text, args.out, regression_count)
    _emit_reasons(reasons)
    sys.exit(_exit_code(regression_count, reasons, args.fail_on_violations, args.validate_plan))


if __name__ == "__main__":
    main()
