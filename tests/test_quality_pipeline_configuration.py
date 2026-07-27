"""Regression tests for canonical analyser and Make pipeline wiring."""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import pytest

from scripts import agent_check

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
LEFTHOOK = (PROJECT_ROOT / "lefthook.yml").read_text(encoding="utf-8")


def _write_executable(path: Path, exit_code: int) -> None:
    path.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
    path.chmod(0o755)


def _write_script(path: Path, content: str) -> None:
    path.write_text(f"#!/bin/sh\n{content}\n", encoding="utf-8")
    path.chmod(0o755)


def test_agent_no_fix_mode_skips_fixers(monkeypatch) -> None:
    sequential_called = False

    def reject_fixers(*_args, **_kwargs):
        nonlocal sequential_called
        sequential_called = True
        return []

    monkeypatch.setattr(agent_check, "_run_sequential", reject_fixers)
    monkeypatch.setattr(agent_check, "_run_parallel", lambda *_args, **_kwargs: [])

    report = agent_check._run_pre_commit(str(PROJECT_ROOT), skip_tests=True, skip_fixers=True)

    assert report.all_passed
    assert sequential_called is False


def test_agent_read_only_analysers_delegate_to_make() -> None:
    analysers = (*agent_check.PRE_COMMIT_LINTERS, *agent_check.PRE_PUSH_ALL)
    direct_commands = [analyser.command for analyser in analysers if analyser.command]
    assert direct_commands
    assert all(command[0] == "make" for command in direct_commands)


def test_safety_tool_version_is_pinned() -> None:
    command, stage = agent_check._build_safety_command(PROJECT_ROOT)
    try:
        assert command[:4] == ["uvx", "--from", "safety==3.8.1", "safety"]
    finally:
        stage.cleanup()


def test_safety_gate_recipe_is_valid_shell() -> None:
    expanded = subprocess.run(
        ["make", "-n", "safety-gate"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    syntax = subprocess.run(
        ["bash", "-n"],
        input=expanded.stdout,
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr


def test_safety_gate_rejects_missing_credentials(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("SAFETY_API_KEY", None)
    env["PATH"] = str(tmp_path)
    result = subprocess.run(
        ["/usr/bin/make", "safety-gate"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "requires SAFETY_API_KEY or infisical CLI" in result.stdout


def test_safety_gate_accepts_explicit_credentials(tmp_path: Path) -> None:
    _write_executable(tmp_path / "uv", 0)
    env = os.environ.copy()
    env["SAFETY_API_KEY"] = "not-a-secret"
    env["PATH"] = str(tmp_path)
    result = subprocess.run(
        ["/usr/bin/make", "safety-gate"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("exit_code", "passes"), [(0, True), (17, False)])
def test_safety_gate_propagates_infisical_result(
    tmp_path: Path, exit_code: int, *, passes: bool
) -> None:
    _write_executable(tmp_path / "infisical", exit_code)
    env = os.environ.copy()
    env.pop("SAFETY_API_KEY", None)
    env["PATH"] = str(tmp_path)
    result = subprocess.run(
        ["/usr/bin/make", "safety-gate"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is passes
    if not passes:
        assert "authenticated Safety scan failed through infisical" in result.stdout


def test_local_safety_skips_when_infisical_has_no_credentials(tmp_path: Path) -> None:
    _write_executable(tmp_path / "infisical", 17)
    env = os.environ.copy()
    env.pop("SAFETY_API_KEY", None)
    env["PATH"] = str(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "safety"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "credentials unavailable through infisical" in result.stdout


def test_local_safety_propagates_authenticated_scan_failure(tmp_path: Path) -> None:
    state = tmp_path / "credential-probed"
    _write_script(
        tmp_path / "infisical",
        f'if [ ! -f "{state}" ]; then : > "{state}"; exit 0; fi\nexit 17',
    )
    env = os.environ.copy()
    env.pop("SAFETY_API_KEY", None)
    env["PATH"] = str(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "safety"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0


def test_make_uses_locked_thresholds_and_trusted_ci_split() -> None:
    assert "--min-coverage $(MIN_COVERAGE)" in MAKEFILE
    assert "--min-coverage 80" not in MAKEFILE
    ci_start = MAKEFILE.index("\nci:") + 1
    ci_body = MAKEFILE[ci_start : MAKEFILE.index("\nci-trusted:")]
    assert "safety-gate" not in ci_body
    assert "ci-trusted: ci safety-gate" in MAKEFILE


def test_blocking_semgrep_uses_only_local_snapshots() -> None:
    semgrep_body = MAKEFILE[MAKEFILE.index("semgrep:  ##") : MAKEFILE.index("semgrep-json:")]
    assert "scripts/semgrep_policy.py --blocking" in semgrep_body
    assert "$(SEMGREP_CONFIGS)" in semgrep_body
    assert "p/python" not in semgrep_body
    assert "uvx --from semgrep==$(SEMGREP_VERSION)" in MAKEFILE


def test_ci_targets_are_split() -> None:
    """CI lanes must expose per-stage canonical targets owned by make."""
    required = ("ci-static", "ci-test-coverage", "ci-test-compat", "ci-property", "ci-package")
    missing = [target for target in required if f"\n{target}:" not in MAKEFILE]
    assert missing == [], f"Makefile missing CI lane targets: {missing}"


def test_analyser_contract_tests_target_exists() -> None:
    """The analyser contract tests target must be a canonical make goal."""
    assert "\nanalyser-contract-tests:" in MAKEFILE


def test_opencode_audit_target_exists() -> None:
    """The OpenCode npm-audit target must be a canonical make goal."""
    assert "\nopencode-audit:" in MAKEFILE


def test_lefthook_glob_alternatives_use_supported_braces() -> None:
    """Pipe-separated globs silently skip matching staged files in Lefthook."""
    glob_lines = [
        line.strip() for line in LEFTHOOK.splitlines() if line.strip().startswith("glob:")
    ]
    assert glob_lines
    assert all("|" not in line for line in glob_lines)
    assert 'glob: "*.{py,yml,yaml,ts}"' in glob_lines
    assert 'glob: ".github/workflows/*.{yml,yaml}"' in glob_lines


def test_mutmut_ignores_repository_infrastructure_tests() -> None:
    """Mutmut's isolated tree cannot collect tests requiring repository tooling."""
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    arguments = set(config["tool"]["mutmut"]["pytest_add_cli_args"])
    required = {
        "--ignore=tests/test_module_coverage.py",
        "--ignore=tests/test_quality_pipeline_configuration.py",
        "--ignore=tests/test_workflow_configuration.py",
    }
    assert required <= arguments
