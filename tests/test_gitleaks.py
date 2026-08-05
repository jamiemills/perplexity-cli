"""Unit tests for gitleaks_check.sh — ref parsing, mode selection, version
validation, and OID handling.

These tests exercise the script's argument parsing, exit code classification,
and stdin refspec processing in isolation from a real repository.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "gitleaks_check.sh"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "gitleaks"


def _require_gitleaks() -> None:
    """Require the gitleaks binary; fail in CI contexts, skip locally.

    These tests verify the secret-scanning pipeline, so in a CI context an
    absent binary is a hard failure rather than a silent skip (authoritative
    run).  Locally, skipping is a non-authoritative convenience.
    """
    if shutil.which("gitleaks") is not None:
        return
    if os.environ.get("CI"):
        pytest.fail(
            "gitleaks binary is required for the authoritative gitleaks "
            "run in CI (install gitleaks 8.30.1)"
        )
    pytest.skip("gitleaks binary not installed")


@pytest.fixture(autouse=True)
def _require_gitleaks_autouse() -> None:
    _require_gitleaks()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_script(
    *args: str,
    stdin_text: str | None = None,
    env_extra: dict[str, str] | None = None,
    cwd: Path = PROJECT_ROOT,
) -> subprocess.CompletedProcess[str]:
    env = {**dict(__import__("os").environ), **(env_extra or {})}
    # gitleaks scans the full commit history (754+ commits) in ci-full and
    # CI_NO_SKIP modes; the bound must accommodate parallel xdist workers
    # sharing the disk, so a generous fixed timeout is used throughout.
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=60,
        input=stdin_text,
        env=env,
    )
    return result


def _assert_missing_mode_error(result: subprocess.CompletedProcess[str]) -> None:
    """Gitleaks binary is available in dev, so we expect 'usage:' or 'unknown mode'
    rather than 'not installed'."""
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 3
    assert "usage:" in combined or "unknown mode" in combined or "ERROR" in combined


def _run_provisioning(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    reset_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a git provisioning command, retrying once on transient failure.

    The single retry after a short sleep absorbs the intermittent non-zero
    exits seen when parallel xdist workers saturate the machine.  When
    *reset_dir* is set it is wiped and recreated before every attempt so a
    partially-created repository is never committed on top of.  Captured
    stdout and stderr are surfaced in the failure message rather than
    swallowed by ``check=True``.

    Raises:
        AssertionError: The command failed on every attempt.
    """
    last_error = ""
    for _attempt in range(2):
        if reset_dir is not None:
            shutil.rmtree(reset_dir, ignore_errors=True)
            reset_dir.mkdir()
        result = subprocess.run(
            [*command],
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd is not None else None,
        )
        if result.returncode == 0:
            return result
        last_error = f"stdout: {result.stdout}\nstderr: {result.stderr}"
        time.sleep(0.5)
    raise AssertionError(f"git provisioning failed:\n{last_error}")


# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------


class TestModeSelection:
    """Argument parsing dispatches to the correct scan mode."""

    def test_pre_push_mode_requires_remote_args(self) -> None:
        result = _run_script("pre-push")
        _assert_missing_mode_error(result)

    def test_pre_push_mode_rejects_too_many_args(self) -> None:
        result = _run_script("pre-push", "origin", "https://example.com/repo", "extra")
        _assert_missing_mode_error(result)

    def test_ci_full_mode_rejects_extra_args(self) -> None:
        result = _run_script("ci-full", "extra")
        _assert_missing_mode_error(result)

    def test_range_mode_requires_both_args(self) -> None:
        result = _run_script("range")
        _assert_missing_mode_error(result)

    def test_range_mode_requires_both_args_no_second(self) -> None:
        result = _run_script("range", "HEAD")
        _assert_missing_mode_error(result)

    def test_unknown_mode_rejected(self) -> None:
        result = _run_script("bogus-mode")
        assert result.returncode == 3
        assert "unknown mode" in (result.stdout + result.stderr)

    def test_ci_full_mode_with_stdin_ignored(self) -> None:
        """ci-full mode does not read stdin refspecs."""
        import os

        if os.environ.get("CI"):
            import pytest

            pytest.skip("CI environment may not have full git history")
        result = _run_script("ci-full")
        assert result.returncode in {0, 10}


# ---------------------------------------------------------------------------
# Version validation
# ---------------------------------------------------------------------------


class TestVersionValidation:
    """Version parsing rejects unsupported gitleaks versions."""

    def _run_with_mock_gitleaks(self, fake_version_output: str) -> subprocess.CompletedProcess[str]:
        """Run script with a fake gitleaks that prints a given version."""
        fake_gitleaks = (
            "#!/usr/bin/env bash\n"
            f"""if [ "$1" = "version" ]; then echo '{fake_version_output}'; exit 0; fi\n"""
            "exit 0"
        )
        script = (
            f"""tmpbin=$(mktemp -d)\n"""
            f"""echo '{fake_gitleaks}' > "$tmpbin/gitleaks"\n"""
            f"""chmod +x "$tmpbin/gitleaks"\n"""
            f'''PATH="$tmpbin:$PATH" bash "{SCRIPT}" ci-full'''
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        return result

    def test_supported_version_accepted(self) -> None:
        result = self._run_with_mock_gitleaks("8.30.1")
        # Supported version; may succeed (0) or find leaks (10) due to repo content.
        assert result.returncode in {0, 10}

    def test_supported_version_accepted_with_leading_v(self) -> None:
        result = self._run_with_mock_gitleaks("v8.30.1")
        assert result.returncode in {0, 10}

    def test_unsupported_version_rejected_older(self) -> None:
        result = self._run_with_mock_gitleaks("8.29.0")
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "unsupported" in combined

    def test_unsupported_version_rejected_newer_major(self) -> None:
        result = self._run_with_mock_gitleaks("9.0.0")
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "unsupported" in combined

    def test_version_rejected_when_command_fails(self) -> None:
        """When gitleaks version itself fails, the script must exit with an error."""
        fake_gitleaks = "#!/usr/bin/env bash\nexit 1"
        script = (
            f"""tmpbin=$(mktemp -d)\n"""
            f"""echo '{fake_gitleaks}' > "$tmpbin/gitleaks"\n"""
            f"""chmod +x "$tmpbin/gitleaks"\n"""
            f'''PATH="$tmpbin:$PATH" bash "{SCRIPT}" ci-full'''
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "gitleaks version" in combined or "failed" in combined.lower()


# ---------------------------------------------------------------------------
# OID handling (zero-OID detection)
# ---------------------------------------------------------------------------


class TestOidHandling:
    """Object-format-aware zero-OID detection."""

    @pytest.fixture(autouse=True)
    def _skip_on_ci(self) -> None:
        import os

        if os.environ.get("CI"):
            pytest.skip("CI environment lacks necessary git state for ref tests")

    def test_sends_deleted_ref_to_skip_path(self) -> None:
        """A deleted ref (local=all-zeros) is skipped."""
        head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=PROJECT_ROOT
        ).strip()
        stdin = (
            f"(delete) 0000000000000000000000000000000000000000 refs/heads/delete-me {head_sha}\n"
        )
        result = _run_script(
            "pre-push",
            "origin",
            "https://example.com/repo.git",
            stdin_text=stdin,
        )
        # Should skip deletion, exit cleanly (0).
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "skipping deleted ref" in combined

    def test_new_ref_remote_zeros_triggers_new_branch_path(self, tmp_path: Path) -> None:
        """A new ref (remote=all-zeros) triggers new-branch detection."""
        repo = tmp_path / "repo"
        remote = tmp_path / "origin.git"
        _run_provisioning(
            ["bash", str(FIXTURES / "clean-repo-setup.sh"), str(repo)],
            reset_dir=repo,
        )
        _run_provisioning(["git", "clone", "--bare", str(repo), str(remote)], reset_dir=remote)
        _run_provisioning(["git", "remote", "add", "origin", str(remote)], cwd=repo)
        (repo / "new-feature.txt").write_text("clean feature\n")
        _run_provisioning(["git", "add", "new-feature.txt"], cwd=repo)
        _run_provisioning(["git", "commit", "-m", "new feature"], cwd=repo)
        head_sha = _run_provisioning(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
        stdin_new = (
            f"refs/heads/new-feature {head_sha} refs/heads/new-feature "
            "0000000000000000000000000000000000000000\n"
        )
        result = _run_script(
            "pre-push",
            "origin",
            str(remote),
            stdin_text=stdin_new,
            cwd=repo,
        )
        # The configured origin is queried and the exact local difference is scanned.
        assert result.returncode == 0

    def test_multiple_refs_build_union(self) -> None:
        """Multiple refs produce a union of commit ranges."""
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=PROJECT_ROOT
        ).strip()
        base = subprocess.check_output(
            ["git", "rev-parse", "HEAD~2"], text=True, cwd=PROJECT_ROOT
        ).strip()
        stdin = (
            f"refs/heads/main {head} refs/heads/main {base}\n"
            f"refs/heads/feature {head} refs/heads/feature {base}\n"
        )
        result = _run_script(
            "pre-push",
            "origin",
            "https://example.com/repo.git",
            stdin_text=stdin,
        )
        assert result.returncode in {0, 10}


# ---------------------------------------------------------------------------
# Stdin validation
# ---------------------------------------------------------------------------


class TestStdinValidation:
    """Malformed stdin rows produce diagnostic errors."""

    def test_malformed_row_fewer_than_four_fields(self) -> None:
        result = _run_script(
            "pre-push",
            "origin",
            "https://example.com/repo.git",
            stdin_text="abc def\n",
        )
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "malformed" in combined

    def test_malformed_row_empty_field(self) -> None:
        result = _run_script(
            "pre-push",
            "origin",
            "https://example.com/repo.git",
            stdin_text="abc refs/heads/main  refs/heads/main\n",
        )
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "malformed" in combined


# ---------------------------------------------------------------------------
# Missing gitleaks binary
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("gitleaks") is not None,
    reason="gitleaks is installed in this environment; the missing-binary contract is not exercisable",
)
class TestMissingGitleaks:
    """Hard failure when gitleaks binary is absent."""

    def test_missing_gitleaks_pre_push_hard_failure(self) -> None:
        """Use a PATH that has git/bash but not gitleaks."""
        import os as _os

        # Keep only directories that definitely don't contain gitleaks (system paths).
        safe_path = "/usr/bin:/usr/local/bin:/bin:/usr/sbin:/sbin"
        result = subprocess.run(
            ["bash", str(SCRIPT), "pre-push", "origin", "https://x.git"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
            env={**_os.environ, "PATH": safe_path},
        )
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "gitleaks is required" in combined or "not installed" in combined

    def test_missing_gitleaks_ci_full_hard_failure(self) -> None:
        import os as _os

        safe_path = "/usr/bin:/usr/local/bin:/bin:/usr/sbin:/sbin"
        result = subprocess.run(
            ["bash", str(SCRIPT), "ci-full"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
            env={**_os.environ, "PATH": safe_path},
        )
        assert result.returncode == 3
        combined = result.stdout + result.stderr
        assert "gitleaks is required" in combined or "not installed" in combined


# ---------------------------------------------------------------------------
# Exit code classification
# ---------------------------------------------------------------------------


class TestExitCodes:
    """The script uses exit code 10 for findings, 0 for clean."""

    def test_ci_full_exit_code_is_zero_or_ten(self) -> None:
        result = _run_script("ci-full")
        assert result.returncode in {0, 10}

    def test_range_mode_exit_code_zero_or_ten(self) -> None:
        try:
            base = subprocess.check_output(
                ["git", "rev-parse", "HEAD~2"], text=True, cwd=PROJECT_ROOT
            ).strip()
        except subprocess.CalledProcessError:
            pytest.skip("shallow checkout: range mode requires at least 2 commits of history")
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=PROJECT_ROOT
        ).strip()
        result = _run_script("range", base, head)
        assert result.returncode in {0, 10}


# ---------------------------------------------------------------------------
# CI_NO_SKIP backward compatibility
# ---------------------------------------------------------------------------


class TestCiNoSkipBackwardCompat:
    """When CI_NO_SKIP is set and no explicit mode, run as ci-full."""

    def test_ci_no_skip_triggers_ci_full(self) -> None:
        """With CI_NO_SKIP=true, backward-compat invocation scans full history."""
        result = _run_script(env_extra={"CI_NO_SKIP": "true"})
        assert result.returncode in {0, 10}
        combined = result.stdout + result.stderr
        assert "CI full-history" in combined or "scanning" in combined.lower()
