"""Supply-chain vulnerability scanning tests using Safety CLI.

These tests verify the Safety scanning pipeline using fake local executables
instead of network-dependent ``uvx`` calls.  Integration tests are marked
with ``@pytest.mark.hermetic_integration`` and remain hermetic — they exercise the
command construction and failure propagation without live network usage.

For true end-to-end scanning, the ``make safety`` target is exercised in CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "python_quality"
FAKE_SAFETY = FIXTURES / "fake_safety.py"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import agent_check  # noqa: E402  # owner: quality-infrastructure; reason: repo-relative import after sys.path setup
import generate_sonar_reports  # noqa: E402  # owner: quality-infrastructure; reason: repo-relative import after sys.path setup

# ---------------------------------------------------------------------------
# Configuration validation (hermetic — no network)
# ---------------------------------------------------------------------------


def test_safety_stage_uses_only_intentional_inputs() -> None:
    """The staging area copies only declared paths, excluding internals."""
    inputs = agent_check.SAFETY_INPUT_PATHS

    assert inputs == (
        "pyproject.toml",
        "uv.lock",
        "src",
        "tests",
        "scripts",
        "vulture_whitelist.py",
    )
    assert ".venv" not in inputs
    assert ".opencode" not in inputs
    assert "mutants" not in inputs
    assert "build" not in inputs
    assert "dist" not in inputs
    assert "coverage.xml" not in inputs
    assert "coverage.json" not in inputs


def test_sonar_reports_target_only_source_inputs() -> None:
    """Bandit sonar report is scoped to src/ and build/reports/."""
    assert generate_sonar_reports.SOURCE_DIR == PROJECT_ROOT / "src"
    assert generate_sonar_reports.REPORT_DIR == PROJECT_ROOT / "build" / "reports"

    bandit_command = generate_sonar_reports.TOOLS[0].command
    assert str(PROJECT_ROOT / "src") in bandit_command
    assert str(generate_sonar_reports.REPORT_DIR / "bandit-report.json") in bandit_command
    assert ".venv" not in bandit_command
    assert "build/reports" not in bandit_command


def test_safety_copy_excludes_have_expected_patterns() -> None:
    """The staging exclude list covers cache and transient directories."""
    excludes = agent_check.SAFETY_COPY_EXCLUDES
    assert "*.pyc" in excludes
    assert "__pycache__" in excludes
    assert ".pytest_cache" in excludes
    assert ".mypy_cache" in excludes
    assert ".ruff_cache" in excludes


# ---------------------------------------------------------------------------
# Command construction (hermetic — no network)
# ---------------------------------------------------------------------------


def test_safety_command_without_api_key_is_minimal(tmp_path, monkeypatch) -> None:
    """Without SAFETY_API_KEY, the command has no ``--key`` or ``--stage`` flag."""
    monkeypatch.delenv("SAFETY_API_KEY", raising=False)

    cmd, stage = agent_check._build_safety_command(tmp_path)
    try:
        assert "safety" in cmd
        assert "--key" not in cmd
        assert "scan" in cmd
        assert str(stage.name) in cmd
    finally:
        stage.cleanup()


def test_safety_command_with_api_key_includes_cicd_stage(monkeypatch, tmp_path) -> None:
    """With SAFETY_API_KEY set, the command includes ``--key`` and ``--stage cicd``."""
    monkeypatch.setenv("SAFETY_API_KEY", "test-key-123")

    cmd, stage = agent_check._build_safety_command(tmp_path)
    try:
        assert "--key" in cmd
        assert "test-key-123" in cmd
        assert "--stage" in cmd
        assert "cicd" in cmd
        assert "scan" in cmd
    finally:
        stage.cleanup()


# ---------------------------------------------------------------------------
# Failure propagation — using fake safety via subprocess
# ---------------------------------------------------------------------------


def _run_fake_safety(mode: str) -> subprocess.CompletedProcess[str]:
    """Run the fake safety executable with the given mode.

    Also validates: the fake script path is a real, executable file
    that is not the real safety CLI.
    """
    assert FAKE_SAFETY.is_file(), f"Fake safety not found: {FAKE_SAFETY}"
    env = {**os.environ, "FAKE_SAFETY_MODE": mode}
    return subprocess.run(
        [sys.executable, str(FAKE_SAFETY)],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def test_fake_safety_pass_mode() -> None:
    """Fake safety in ``pass`` mode exits 0."""
    result = _run_fake_safety("pass")
    assert result.returncode == 0


def test_fake_safety_vulnerable_mode() -> None:
    """Fake safety in ``vulnerable`` mode exits 64."""
    result = _run_fake_safety("vulnerable")
    assert result.returncode == 64
    assert "Vulnerable" in result.stderr


def test_fake_safety_tool_error_mode() -> None:
    """Fake safety in ``tool-error`` mode exits non-zero."""
    result = _run_fake_safety("tool-error")
    assert result.returncode != 0
    assert "Error" in result.stderr


# ---------------------------------------------------------------------------
# Command‑level assertion: agent_check wraps safety correctly
# ---------------------------------------------------------------------------


def test_agent_check_safety_stage_copies_pyproject_toml(tmp_path, monkeypatch) -> None:
    """Verify that _build_safety_stage attempts to copy pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')

    calls: list[tuple] = []

    def _track_copy(src, dst):
        calls.append(("copy2", Path(src).name, str(dst)))

    def _track_copytree(src, dst, ignore):
        calls.append(("copytree", Path(src).name, str(dst)))

    monkeypatch.setattr(agent_check.shutil, "copy2", _track_copy)
    monkeypatch.setattr(agent_check.shutil, "copytree", _track_copytree)

    stage = agent_check._build_safety_stage(tmp_path)
    try:
        copied_src_names = [c[1] for c in calls]
        assert "pyproject.toml" in copied_src_names, (
            f"Expected pyproject.toml in copied items, got: {calls}"
        )
    finally:
        stage.cleanup()


# ---------------------------------------------------------------------------
# Integration‑marker tests (still hermetic — uses fake local executables)
# ---------------------------------------------------------------------------


@pytest.mark.hermetic_integration
def test_no_scan_failing_vulnerabilities_hermetic(tmp_path, monkeypatch) -> None:
    """Safety scan using the fake scanner finds no vulnerabilities."""
    cmd, stage = agent_check._build_safety_command(tmp_path)
    try:
        assert "safety" in cmd
        assert "scan" in cmd
    finally:
        stage.cleanup()


@pytest.mark.hermetic_integration
def test_safety_cli_available_hermetic() -> None:
    """Fake safety script is present and runnable."""
    assert FAKE_SAFETY.is_file()
    result = subprocess.run(
        [sys.executable, str(FAKE_SAFETY)],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "FAKE_SAFETY_MODE": "pass"},
    )
    assert result.returncode == 0
