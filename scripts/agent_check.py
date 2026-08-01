"""Run an agent-oriented analyser subset and produce a unified report.

Designed for coding agents: instead of discovering failures one-by-one
through sequential hooks, this script runs selected analysers concurrently,
captures all output, and prints a single aggregated report.  The agent
then addresses all issues in one pass.

Usage
-----
    python scripts/agent_check.py pre-commit             # agent pre-commit subset
    python scripts/agent_check.py pre-commit --files f1.py f2.py  # scoped
    python scripts/agent_check.py pre-push               # agent pre-push subset
    python scripts/agent_check.py --json pre-commit      # machine-readable output
    python scripts/agent_check.py --no-fix pre-commit    # read-only checks
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404  # owner: quality-infrastructure; reason: configured analyser argv runs without a shell
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

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
    command_builder: Callable[[Path], tuple[list[str], TemporaryDirectory[str] | None]] | None = (
        None
    )


@dataclass(frozen=True, slots=True)
class PreCommitOptions:
    """Controls which pre-commit pipeline stages run."""

    run_tests: bool = True
    run_fixers: bool = True


SAFETY_INPUT_PATHS: tuple[str, ...] = (
    "pyproject.toml",
    "uv.lock",
    "src",
    "tests",
    "scripts",
    "vulture_whitelist.py",
)
SAFETY_COPY_EXCLUDES: tuple[str, ...] = (
    "*.egg-info",
    "*.pyc",
    "*.pyo",
    ".coverage*",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
)


def _build_safety_stage(cwd: Path) -> TemporaryDirectory[str]:
    stage = TemporaryDirectory(prefix="pxcli-safety-")
    stage_root = Path(stage.name)

    for relative_path in SAFETY_INPUT_PATHS:
        source_path = cwd / relative_path
        if not source_path.exists():
            continue

        destination_path = stage_root / relative_path
        if source_path.is_dir():
            shutil.copytree(
                source_path,
                destination_path,
                ignore=shutil.ignore_patterns(*SAFETY_COPY_EXCLUDES),
            )
        else:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)

    return stage


def _build_safety_command(cwd: Path) -> tuple[list[str], TemporaryDirectory[str]]:
    stage = _build_safety_stage(cwd)
    stage_root = Path(stage.name)
    command = ["uvx", "--from", "safety==3.8.1", "safety"]
    safety_api_key = os.environ.get("SAFETY_API_KEY")
    if safety_api_key:
        command.extend(["--key", safety_api_key, "--stage", "cicd"])
    command.extend(["scan", "--target", str(stage_root)])
    return command, stage


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
    Analyser("pyright", ["make", "typecheck-pyright"]),
    Analyser("ty", ["make", "typecheck"]),
    Analyser("bandit", ["make", "bandit"]),
    Analyser("vulture", ["make", "vulture"]),
    Analyser("radon-cc", ["make", "complexity-cc"]),
    Analyser("radon-mi", ["make", "complexity-mi"]),
    Analyser("semgrep", ["make", "semgrep"]),
    Analyser("format-check", ["make", "format-check"]),
    Analyser("lint", ["make", "lint"]),
)

PRE_COMMIT_TESTS: tuple[Analyser, ...] = (
    Analyser("test", ["uv", "run", "pytest", "tests/", "-n", "auto", "-v", "--tb=long"]),
)

# Agent pre-push subset: all independent and run in parallel.
PRE_PUSH_ALL: tuple[Analyser, ...] = (
    Analyser("test-coverage", ["make", "test-coverage"]),
    Analyser("safety", [], command_builder=_build_safety_command),
    Analyser("fuzz", ["make", "test-fuzz"]),
    Analyser("arch-check", ["make", "arch-check"]),
    Analyser("coupling-check", ["make", "coupling-check"]),
    Analyser("test-property", ["make", "test-property-push"]),
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

    results: list[AnalyserResult] = field(default_factory=list[AnalyserResult])
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
    cleanup_target: TemporaryDirectory[str] | None = None
    try:
        if analyser.command_builder is not None:
            cmd, cleanup_target = analyser.command_builder(Path(cwd))

        proc = subprocess.run(  # nosec B603  # owner: quality-infrastructure; reason: configured analyser argv cannot replace the executable and uses no shell
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=600,
            check=False,
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
    except OSError as error:
        detail = (
            f"Command not found: {cmd[0]}"
            if isinstance(error, FileNotFoundError)
            else f"Could not run analyser: {error}"
        )
        return AnalyserResult(
            name=analyser.name,
            command=cmd,
            passed=False,
            duration_s=time.monotonic() - start,
            stderr=detail,
        )
    finally:
        if cleanup_target is not None:
            cleanup_target.cleanup()


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
    if not analysers:
        return []

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
    lines.append(f"    $ {' '.join(_redact_command(result.command))}")
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


def _redact_command(command: list[str]) -> list[str]:
    redacted = command[:]
    for index, value in enumerate(redacted):
        if value == "--key" and index + 1 < len(redacted):
            redacted[index + 1] = "[REDACTED]"
        elif value.startswith("--key="):
            redacted[index] = "--key=[REDACTED]"
    return redacted


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


def _run_pre_commit(
    cwd: str,
    *,
    options: PreCommitOptions | None = None,
    **legacy_options: bool,
) -> RunReport:
    """Run the pre-commit pipeline: fixers → linters → tests."""
    selected_options = _normalise_pre_commit_options(options, legacy_options)
    t0 = time.monotonic()
    all_results: list[AnalyserResult] = []

    if selected_options.run_fixers:
        all_results.extend(_run_sequential(PRE_COMMIT_FIXERS, cwd))
    all_results.extend(_run_parallel(PRE_COMMIT_LINTERS, cwd))
    if selected_options.run_tests:
        all_results.extend(_run_parallel(PRE_COMMIT_TESTS, cwd))

    return RunReport(
        results=all_results,
        total_duration_s=time.monotonic() - t0,
    )


def _normalise_pre_commit_options(
    options: PreCommitOptions | None,
    legacy_options: dict[str, bool],
) -> PreCommitOptions:
    """Translate the established skip keywords into positive stage options."""
    unknown = set(legacy_options) - {"skip_tests", "skip_fixers"}
    if unknown:
        unexpected = next(iter(sorted(unknown)))
        msg = f"_run_pre_commit() got an unexpected keyword argument '{unexpected}'"
        raise TypeError(msg)
    if options is not None and legacy_options:
        msg = "options cannot be combined with skip_tests or skip_fixers"
        raise TypeError(msg)
    if options is not None:
        return options
    return PreCommitOptions(
        run_tests=not legacy_options.get("skip_tests"),
        run_fixers=not legacy_options.get("skip_fixers"),
    )


def _run_pre_push(cwd: str) -> RunReport:
    """Run the pre-push pipeline: all analysers in parallel."""
    t0 = time.monotonic()
    all_results = _run_parallel(PRE_PUSH_ALL, cwd)
    return RunReport(
        results=all_results,
        total_duration_s=time.monotonic() - t0,
    )


def _run_safety(cwd: str) -> RunReport:
    t0 = time.monotonic()
    analyser = Analyser("safety", [], command_builder=_build_safety_command)
    return RunReport(
        results=[_run_one(analyser, cwd)],
        total_duration_s=time.monotonic() - t0,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(raw: list[str]) -> tuple[bool, str | None, bool, bool]:
    scopes = {"pre-commit", "pre-push", "safety"}
    scope = next((argument for argument in raw if argument in scopes), None)
    return "--json" in raw, scope, "--no-tests" in raw, "--no-fix" in raw


def main() -> None:
    json_mode, scope, skip_tests, skip_fixers = _parse_args(sys.argv[1:])

    if scope is None:
        print(
            "Usage: agent_check.py [--json] [--no-tests] [--no-fix] pre-commit|pre-push|safety",
            file=sys.stderr,
        )
        sys.exit(2)

    cwd = str(PROJECT_ROOT)

    if scope == "pre-commit":
        options = PreCommitOptions(run_tests=not skip_tests, run_fixers=not skip_fixers)
        report = _run_pre_commit(cwd, options=options)
    elif scope == "safety":
        report = _run_safety(cwd)
    else:
        report = _run_pre_push(cwd)

    if json_mode:
        print(_format_json(report))
    else:
        print(_format_report(report))

    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
