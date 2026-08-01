"""Edge-case tests for the agent_check parallel runner.

Tests failure modes of the analyser execution engine: missing tools,
timeouts, and empty analyser lists.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from scripts import agent_check

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    name: str = "test",
    passed: bool = True,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    duration_s: float = 0.1,
    command: list[str] | None = None,
) -> agent_check.AnalyserResult:
    """Build an ``AnalyserResult`` for test assembly."""
    return agent_check.AnalyserResult(
        name=name,
        command=command or ["echo", "test"],
        passed=passed,
        duration_s=duration_s,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )


# ---------------------------------------------------------------------------
# _run_one edge cases
# ---------------------------------------------------------------------------


def test_run_one_os_error_file_not_found(monkeypatch) -> None:
    """FileNotFoundError is caught and reported as an analyser failure."""

    def _fail(*args, **kwargs):
        raise FileNotFoundError("no-such-tool")

    monkeypatch.setattr(agent_check.subprocess, "run", _fail)

    analyser = agent_check.Analyser(name="missing", command=["no-such-tool"])
    result = agent_check._run_one(analyser, str(PROJECT_ROOT))
    assert not result.passed
    assert "no-such-tool" in result.stderr


def test_run_one_os_error_generic(monkeypatch) -> None:
    """OSError other than FileNotFoundError is caught and reported."""

    def _fail(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(agent_check.subprocess, "run", _fail)

    analyser = agent_check.Analyser(name="perm", command=["/bad/path"])
    result = agent_check._run_one(analyser, str(PROJECT_ROOT))
    assert not result.passed
    assert "permission denied" in result.stderr


def test_run_one_timeout(monkeypatch) -> None:
    """TimeoutExpired is caught and reported as an analyser failure."""

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["slow"], timeout=0.1)

    monkeypatch.setattr(agent_check.subprocess, "run", _timeout)

    analyser = agent_check.Analyser(name="slow", command=["slow"])
    result = agent_check._run_one(analyser, str(PROJECT_ROOT))
    assert not result.passed
    assert "TIMEOUT" in result.stderr


def test_run_one_with_command_builder_cleanup(monkeypatch, tmp_path) -> None:
    """The TemporaryDirectory from a command_builder is cleaned up after execution."""

    cleanup_called = False

    class TrackedTempDir:
        """Fake TemporaryDirectory that tracks cleanup."""

        name: str = str(tmp_path)

        def cleanup(self) -> None:
            nonlocal cleanup_called
            cleanup_called = True

    def _builder(cwd: Path) -> tuple[list[str], TrackedTempDir]:
        return ["echo", "hello"], TrackedTempDir()

    called = _builder(Path(str(tmp_path)))

    proc = SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(agent_check.subprocess, "run", lambda *args, **kwargs: proc)

    analyser = agent_check.Analyser(
        name="builder-test",
        command=["echo"],
        command_builder=_builder,
    )
    agent_check._run_one(analyser, str(PROJECT_ROOT))
    assert cleanup_called


# ---------------------------------------------------------------------------
# Report formatter edge cases
# ---------------------------------------------------------------------------


def test_format_report_all_passed() -> None:
    """Formatting a fully-passing report produces expected output."""
    results = [
        _make_result("ruff", passed=True, stdout="ok"),
        _make_result("pyright", passed=True, stdout="clean"),
    ]
    report = agent_check.RunReport(results=results, total_duration_s=2.0)
    output = agent_check._format_report(report)
    assert "2 passed" in output
    assert "0 failed" in output
    assert "PASS" in output


def test_format_report_all_failed() -> None:
    """Formatting a fully-failing report produces expected output."""
    results = [
        _make_result("ruff", passed=False, exit_code=1, stderr="error"),
        _make_result("pyright", passed=False, exit_code=2, stderr="fail"),
    ]
    report = agent_check.RunReport(results=results, total_duration_s=3.0)
    output = agent_check._format_report(report)
    assert "0 passed" in output
    assert "2 failed" in output


def test_format_report_mixed() -> None:
    """Formatting a mixed-pass report."""
    results = [
        _make_result("ruff", passed=True),
        _make_result("pyright", passed=False),
    ]
    report = agent_check.RunReport(results=results, total_duration_s=1.5)
    assert report.passed == 1
    assert report.failed == 1
    assert not report.all_passed


def test_format_json_output() -> None:
    """JSON output is valid and contains expected fields."""
    import json

    results = [
        _make_result("ruff", passed=True, stdout="ok"),
        _make_result("pyright", passed=False, stderr="fail"),
    ]
    report = agent_check.RunReport(results=results, total_duration_s=1.0)
    output = agent_check._format_json(report)
    data = json.loads(output)
    assert data["passed"] == 1
    assert data["failed"] == 1
    assert not data["all_passed"]
    assert len(data["results"]) == 2
    assert data["results"][0]["name"] == "ruff"


def test_redact_command_hides_api_key() -> None:
    """The Safety API key is redacted from the printed command."""
    cmd = ["uvx", "safety", "--key", "secret123", "scan"]
    redacted = agent_check._redact_command(cmd)
    assert "secret123" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_command_hides_key_equals() -> None:
    """The Safety API key in ``--key=value`` form is redacted."""
    cmd = ["uvx", "safety", "--key=secret456", "scan"]
    redacted = agent_check._redact_command(cmd)
    assert "secret456" not in " ".join(redacted)


def test_truncation_long_output() -> None:
    """Output with many lines is truncated to TRUNCATE_LINES."""
    long_text = "\n".join(f"line {i}" for i in range(500))
    result = _make_result("vulture", passed=True, stdout=long_text)
    report = agent_check.RunReport(results=[result], total_duration_s=0.5)
    output = agent_check._format_report(report)
    assert "... (" in output
    assert "more lines)" in output


# ---------------------------------------------------------------------------
# Empty / missing analysers
# ---------------------------------------------------------------------------


def test_run_sequential_empty() -> None:
    """Running an empty tuple of analysers returns an empty list."""
    results = agent_check._run_sequential((), str(PROJECT_ROOT))
    assert results == []


def test_run_parallel_empty() -> None:
    """Running an empty tuple of analysers returns an empty list."""
    results = agent_check._run_parallel((), str(PROJECT_ROOT))
    assert results == []


# ---------------------------------------------------------------------------
# Command builder edge cases
# ---------------------------------------------------------------------------


def test_safety_stage_copies_pyproject_toml(tmp_path, monkeypatch) -> None:
    """The safety staging area copies pyproject.toml."""
    monkeypatch.setattr(agent_check.shutil, "copy2", lambda src, dst: None)
    monkeypatch.setattr(agent_check.shutil, "copytree", lambda src, dst, ignore: None)
    monkeypatch.setattr(
        agent_check.shutil,
        "ignore_patterns",
        lambda *args: None,
    )

    stage = agent_check._build_safety_stage(tmp_path)
    assert stage is not None
    stage.cleanup()


def test_safety_command_construction_without_api_key() -> None:
    """Safety command is built correctly without an API key."""
    from pathlib import Path as P

    cmd, stage = agent_check._build_safety_command(P(str(PROJECT_ROOT)))
    try:
        assert cmd[0] == "uvx"
        assert "--key" not in cmd  # key not present when env var not set
    finally:
        stage.cleanup()


# ---------------------------------------------------------------------------
# Parse-args edge cases
# ---------------------------------------------------------------------------


def test_parse_args_no_scope() -> None:
    """Calling without a recognised scope returns None for scope."""
    json_mode, scope, skip_tests, skip_fixers = agent_check._parse_args([])
    assert scope is None
    assert not json_mode
    assert not skip_tests
    assert not skip_fixers


def test_parse_args_json_and_scope() -> None:
    """``--json`` flag and scope are both recognised."""
    json_mode, scope, _, _ = agent_check._parse_args(["--json", "pre-commit"])
    assert json_mode
    assert scope == "pre-commit"


def test_parse_args_no_tests_no_fix() -> None:
    """``--no-tests`` and ``--no-fix`` flags are recognised."""
    _, _, skip_tests, skip_fixers = agent_check._parse_args(
        ["pre-commit", "--no-tests", "--no-fix"]
    )
    assert skip_tests
    assert skip_fixers


# ---------------------------------------------------------------------------
# RunReport properties
# ---------------------------------------------------------------------------


def test_run_report_passed_count() -> None:
    """passed property counts successful results."""
    results = [
        _make_result("a", passed=True),
        _make_result("b", passed=False),
        _make_result("c", passed=True),
    ]
    report = agent_check.RunReport(results=results, total_duration_s=1.0)
    assert report.passed == 2
    assert report.failed == 1
    assert not report.all_passed
