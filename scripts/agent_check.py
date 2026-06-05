"""Run all analysers in parallel and produce a unified report.

Designed for coding agents: instead of discovering failures one-by-one
through sequential hooks, this script runs every analyser simultaneously,
captures all output, and prints a single aggregated report.  The agent
then addresses all issues in one pass.

Usage
-----
    python scripts/agent_check.py pre-commit             # all pre-commit analysers
    python scripts/agent_check.py pre-commit --files f1.py f2.py  # scoped
    python scripts/agent_check.py pre-push               # all pre-push analysers
    python scripts/agent_check.py --json pre-commit      # machine-readable output
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Analyser definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Analyser:
    """Definition of a single analyser: name, command, and whether it modifies files."""

    name: str
    command: list[str]
    fixer: bool = False  # True if this analyser modifies source files


# Pre-commit analysers: fixers run first (sequential), then linters (parallel), then tests.
PRE_COMMIT_FIXERS: tuple[Analyser, ...] = (
    Analyser("ruff-format", ["uv", "run", "ruff", "format", "src", "tests"], fixer=True),
    Analyser(
        "ruff-check-fix",
        ["uv", "run", "ruff", "check", "--fix", "src", "tests"],
        fixer=True,
    ),
)

PRE_COMMIT_LINTERS: tuple[Analyser, ...] = (
    Analyser("pyright", ["uv", "run", "pyright", "src/"]),
    Analyser("ty", ["uv", "run", "ty", "check", "src"]),
    Analyser(
        "bandit",
        ["uvx", "--from", "bandit", "bandit", "-c", "pyproject.toml", "-r", "src/", "-ll", "-ii"],
    ),
    Analyser(
        "vulture",
        ["uv", "run", "vulture", "src/", "vulture_whitelist.py", "--min-confidence", "80"],
    ),
    Analyser("radon-cc", ["uv", "run", "radon", "cc", "src/", "-s", "-n", "B"]),
    Analyser("radon-mi", ["uv", "run", "radon", "mi", "src/", "-s", "-n", "B"]),
    Analyser(
        "semgrep",
        [
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
            "python.lang.maintainability.useless-innerfunction.useless-inner-function",
            "--exclude",
            "tests/",
            "--error",
            "--metrics=off",
            ".",
        ],
    ),
    Analyser("format-check", ["uv", "run", "ruff", "format", "--check", "src", "tests"]),
    Analyser("lint", ["uv", "run", "ruff", "check", "src", "tests"]),
)

PRE_COMMIT_TESTS: tuple[Analyser, ...] = (
    Analyser("test", ["uv", "run", "pytest", "tests/", "-v", "--tb=long"]),
)

# Pre-push analysers: all independent, all parallel.
PRE_PUSH_ALL: tuple[Analyser, ...] = (
    Analyser(
        "test-coverage",
        [
            "uv",
            "run",
            "pytest",
            "tests/",
            "-v",
            "--tb=long",
            "--cov=perplexity_cli",
            "--cov-report=term-missing",
            "--cov-report=json",
            "--cov-report=xml:coverage.xml",
        ],
    ),
    Analyser("safety", ["uvx", "safety", "scan", "--target", "."]),
    Analyser(
        "fuzz", ["uv", "run", "pytest", "tests/test_fuzz.py", "-v", "--tb=long", "-m", "fuzz"]
    ),
    Analyser("arch-check", ["uv", "run", "python", "scripts/check_architecture.py"]),
    Analyser("coupling-check", ["uv", "run", "python", "scripts/check_coupling.py"]),
    Analyser(
        "test-property",
        [
            "uv",
            "run",
            "pytest",
            "tests/test_property.py",
            "-v",
            "--tb=short",
            "--hypothesis-profile=push",
        ],
    ),
)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class AnalyserResult:
    """Result of a single analyser run."""

    name: str
    command: list[str]
    passed: bool
    duration_s: float
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""


@dataclass
class RunReport:
    """Aggregated report for an entire check run."""

    results: list[AnalyserResult] = field(default_factory=list)
    total_duration_s: float = 0.0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _run_one(analyser: Analyser, cwd: str) -> AnalyserResult:
    """Run a single analyser and return its result."""
    start = time.monotonic()
    cmd = analyser.command
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=600,
        )
        return AnalyserResult(
            name=analyser.name,
            command=cmd,
            passed=proc.returncode == 0,
            duration_s=time.monotonic() - start,
            exit_code=proc.returncode,
            stdout=proc.stdout.strip(),
            stderr=proc.stderr.strip(),
        )
    except subprocess.TimeoutExpired:
        return AnalyserResult(
            name=analyser.name,
            command=cmd,
            passed=False,
            duration_s=time.monotonic() - start,
            stderr="TIMEOUT after 600s",
        )
    except FileNotFoundError:
        return AnalyserResult(
            name=analyser.name,
            command=cmd,
            passed=False,
            duration_s=time.monotonic() - start,
            stderr=f"Command not found: {cmd[0]}",
        )


def _run_sequential(analysers: tuple[Analyser, ...], cwd: str) -> list[AnalyserResult]:
    """Run analysers sequentially, stopping at first failure for fixers."""
    results: list[AnalyserResult] = []
    for a in analysers:
        result = _run_one(a, cwd)
        results.append(result)
        if not result.passed and a.fixer:
            break  # Don't run more fixers if one failed
    return results


def _run_parallel(analysers: tuple[Analyser, ...], cwd: str) -> list[AnalyserResult]:
    """Run analysers in parallel, collecting all results."""
    from concurrent.futures import ThreadPoolExecutor

    results: list[AnalyserResult] = []
    with ThreadPoolExecutor(max_workers=len(analysers)) as executor:
        futures = {executor.submit(_run_one, a, cwd): a for a in analysers}
        for future in futures:
            results.append(future.result())

    # Sort by name for deterministic output
    results.sort(key=lambda r: r.name)
    return results


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


SEP = "━" * 72


def _format_report(report: RunReport) -> str:
    """Format a RunReport as comprehensive human-readable text."""
    lines: list[str] = []

    lines.append(
        f"Agent check ({report.passed} passed, {report.failed} failed, "
        f"{report.total_duration_s:.1f}s total)"
    )
    lines.append("")

    for i, r in enumerate(report.results):
        _append_analyser_section(lines, i, len(report.results), r)

    lines.append(SEP)
    lines.append(
        f"Final: {report.passed} passed, {report.failed} failed in {report.total_duration_s:.1f}s"
    )

    return "\n".join(lines)


def _append_analyser_section(
    lines: list[str], index: int, total: int, result: AnalyserResult
) -> None:
    """Append a full section for a single analyser result."""
    status = "PASS" if result.passed else "FAIL"
    lines.append(
        f"[{index + 1}/{total}] {result.name} — {status} "
        f"({result.duration_s:.1f}s, exit {result.exit_code})"
    )
    lines.append(f"    $ {' '.join(result.command)}")
    lines.append(SEP)

    _append_output_block(lines, result.stdout, "stdout", "stderr" if result.stderr else None)
    _append_output_block(lines, result.stderr, "stderr", None)

    lines.append("")


def _append_output_block(lines: list[str], output: str, label: str, next_label: str | None) -> None:
    """Append a block of output text, optionally with a separator label."""
    if not output:
        if _is_final_empty_block(label, next_label):
            lines.append("    (no output)")
        return

    if label == "stderr" and next_label:
        lines.append("    --- stderr ---")

    _append_truncated_lines(lines, output)


def _is_final_empty_block(label: str, next_label: str | None) -> bool:
    """Return True if this is the last block and it's empty."""
    return label == "stderr" and next_label is None


TRUNCATE_LINES = 200


def _append_truncated_lines(lines: list[str], output: str) -> None:
    output_lines = output.split("\n")
    for line in output_lines[:TRUNCATE_LINES]:
        lines.append(f"    {line}")
    if len(output_lines) > TRUNCATE_LINES:
        lines.append(f"    ... ({len(output_lines) - TRUNCATE_LINES} more lines)")


def _format_json(report: RunReport) -> str:
    """Format a RunReport as JSON."""
    return json.dumps(
        {
            "passed": report.passed,
            "failed": report.failed,
            "total_duration_s": round(report.total_duration_s, 1),
            "all_passed": report.all_passed,
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "duration_s": round(r.duration_s, 1),
                    "stdout": r.stdout[:2000] if r.stdout else "",
                    "stderr": r.stderr[:2000] if r.stderr else "",
                }
                for r in report.results
            ],
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Pipeline runners
# ---------------------------------------------------------------------------


def _run_pre_commit(cwd: str, skip_tests: bool = False) -> RunReport:
    """Run the pre-commit pipeline: fixers → linters → tests."""
    t0 = time.monotonic()
    all_results: list[AnalyserResult] = []

    all_results.extend(_run_sequential(PRE_COMMIT_FIXERS, cwd))
    all_results.extend(_run_parallel(PRE_COMMIT_LINTERS, cwd))
    if not skip_tests:
        all_results.extend(_run_parallel(PRE_COMMIT_TESTS, cwd))

    return RunReport(
        results=all_results,
        total_duration_s=time.monotonic() - t0,
    )


def _run_pre_push(cwd: str) -> RunReport:
    """Run the pre-push pipeline: all analysers in parallel."""
    t0 = time.monotonic()
    all_results = _run_parallel(PRE_PUSH_ALL, cwd)
    return RunReport(
        results=all_results,
        total_duration_s=time.monotonic() - t0,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(raw: list[str]) -> tuple[bool, str | None, bool]:
    json_mode = False
    scope: str | None = None
    skip_tests = False
    for arg in raw:
        if arg == "--json":
            json_mode = True
        elif arg == "--no-tests":
            skip_tests = True
        elif arg in ("pre-commit", "pre-push"):
            scope = arg
    return json_mode, scope, skip_tests


def main() -> None:
    json_mode, scope, skip_tests = _parse_args(sys.argv[1:])

    if scope is None:
        print("Usage: agent_check.py [--json] [--no-tests] pre-commit|pre-push", file=sys.stderr)
        sys.exit(2)

    cwd = str(PROJECT_ROOT)

    if scope == "pre-commit":
        report = _run_pre_commit(cwd, skip_tests=skip_tests)
    else:
        report = _run_pre_push(cwd)

    if json_mode:
        print(_format_json(report))
    else:
        print(_format_report(report))

    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
